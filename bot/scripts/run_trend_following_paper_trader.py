"""Paper trader for daily MA-ensemble trend following on BTC/ETH spot.

No real orders are ever sent. The loop watches confirmed daily candles,
computes the trend signal, and applies simulated fills to a persistent
paper book. Every simulated order still passes the pre-trade RiskGate and
is recorded in the execution-quality (TCA) log, so the paper run exercises
the exact safety path a live trader would use.

Usage:
    python -m scripts.run_trend_following_paper_trader --backtest   # sanity backtest
    python -m scripts.run_trend_following_paper_trader              # paper loop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.config import settings
from app.core.execution_quality import ExecutionQualityLog, ExecutionRecord
from app.core.risk_gate import AccountState, OrderIntent, RiskGate, build_risk_gate_from_settings
from app.core.runtime_events import add_event
from app.core.trend_following import (
    DEFAULT_MA_PERIODS,
    PaperBook,
    affordable_quantity,
    apply_paper_fill,
    backtest_trend_following,
    evaluate_trend,
    plan_rebalance,
)
from app.exchange.public_market_data import OKXPublicMarketData

STRATEGY_NAME = "Daily MA Trend Following (paper)"
MAX_CANDLES_PER_REQUEST = 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default="BTC-USDT,ETH-USDT", help="Comma-separated spot pairs.")
    parser.add_argument("--allocation-usd", type=float, default=1000.0, help="Paper allocation per pair.")
    parser.add_argument("--ma-periods", default="20,50,100", help="Comma-separated SMA periods (days).")
    parser.add_argument("--fee-pct", type=float, default=0.10, help="Taker fee percent per side.")
    parser.add_argument("--min-trade-usd", type=float, default=25.0)
    parser.add_argument("--poll-seconds", type=int, default=3600)
    parser.add_argument("--duration-seconds", type=int, default=0, help="0 runs until interrupted.")
    parser.add_argument("--state-file", default="state/trend_following_paper.json")
    parser.add_argument("--backtest", action="store_true", help="Run a historical backtest and exit.")
    parser.add_argument("--backtest-days", type=int, default=400)
    return parser


def parse_pairs(raw: str) -> tuple[str, ...]:
    pairs = tuple(item.strip().upper() for item in raw.split(",") if item.strip())
    if not pairs:
        raise ValueError("at least one pair is required")
    for pair in pairs:
        if pair.endswith("-SWAP"):
            raise ValueError(f"{pair}: use spot pairs (e.g. BTC-USDT); this strategy is long/flat spot")
    return pairs


def parse_ma_periods(raw: str) -> tuple[int, ...]:
    try:
        periods = tuple(sorted({int(item.strip()) for item in raw.split(",") if item.strip()}))
    except ValueError as exc:
        raise ValueError(f"invalid ma periods: {raw!r}") from exc
    if not periods or any(period <= 1 for period in periods):
        raise ValueError("ma periods must be integers greater than 1")
    return periods


async def fetch_daily_candles(
    market_data: OKXPublicMarketData,
    pair: str,
    *,
    days: int,
) -> list[dict[str, Any]]:
    """Fetch ascending confirmed daily candles, paginating into history."""

    collected: dict[str, dict[str, Any]] = {}
    after: str | None = None
    while len(collected) < days:
        rows = await market_data.get_candles(
            pair,
            "1D",
            limit=MAX_CANDLES_PER_REQUEST,
            after=after,
        )
        if not rows:
            break
        for row in rows:
            if str(row.get("confirm", "1")) == "1":
                collected[str(row["timestamp"])] = row
        oldest = min(rows, key=lambda item: int(item["timestamp"]))
        next_after = str(oldest["timestamp"])
        if next_after == after:
            break
        after = next_after

    ordered = sorted(collected.values(), key=lambda item: int(item["timestamp"]))
    return ordered[-days:]


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


def load_state(path: Path, *, pairs: Sequence[str], allocation_usd: float) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state file is not a JSON object")
    except FileNotFoundError:
        state = {}
    except (OSError, json.JSONDecodeError, ValueError):
        raise SystemExit(f"state file {path} is corrupt; move it aside before restarting")

    if not state:
        state = {
            "strategy": STRATEGY_NAME,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "book": PaperBook(cash_usd=allocation_usd * len(pairs)).to_payload(),
            "processed_candle_ts": {},
            "trades": [],
            "equity_history": [],
        }
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".paper_state_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def daily_realized_pnl_usd(state: dict[str, Any], *, now: datetime) -> float:
    today = now.date().isoformat()
    total = 0.0
    for trade in state.get("trades", []):
        occurred = str(trade.get("occurred_at") or "")
        if occurred.startswith(today) and trade.get("realized_pnl_usd") is not None:
            total += float(trade["realized_pnl_usd"])
    return total


# --------------------------------------------------------------------------- #
# One evaluation pass for one pair
# --------------------------------------------------------------------------- #


async def process_pair(
    *,
    pair: str,
    market_data: OKXPublicMarketData,
    state: dict[str, Any],
    risk_gate: RiskGate,
    execution_log: ExecutionQualityLog,
    ma_periods: Sequence[int],
    allocation_usd: float,
    fee_pct: float,
    min_trade_usd: float,
) -> dict[str, Any] | None:
    """Evaluate the latest confirmed daily candle. Returns the trade if any."""

    candles = await fetch_daily_candles(market_data, pair, days=max(ma_periods) + 5)
    if len(candles) <= max(ma_periods):
        add_event(
            event="paper_trend_skip",
            level="warning",
            pair=pair,
            strategy=STRATEGY_NAME,
            message=f"not enough daily candles for {pair} ({len(candles)})",
        )
        return None

    latest = candles[-1]
    latest_ts = str(latest["timestamp"])
    if state["processed_candle_ts"].get(pair) == latest_ts:
        return None  # no new confirmed daily candle yet

    closes = [float(row["close"]) for row in candles]
    signal = evaluate_trend(pair, closes, ma_periods=ma_periods)
    state["processed_candle_ts"][pair] = latest_ts

    book = PaperBook.from_payload(state["book"])
    ticker = await market_data.get_ticker(pair)
    market_price = float(ticker["mid_price"] or ticker["last"])
    if market_price <= 0:
        return None

    order = plan_rebalance(
        inst_id=pair,
        target_fraction=signal.target_fraction,
        allocation_usd=allocation_usd,
        current_quantity=book.position(pair).quantity,
        price=market_price,
        min_trade_usd=min_trade_usd,
    )

    add_event(
        event="paper_trend_signal",
        pair=pair,
        strategy=STRATEGY_NAME,
        timeframe="1D",
        message=(
            f"{pair} close {signal.close:,.2f}, votes {signal.votes}/{signal.total},"
            f" target {signal.target_fraction:.2f}"
            + ("" if order else " (no rebalance needed)")
        ),
        details={"votes": signal.votes, "target_fraction": signal.target_fraction},
    )
    if order is None:
        return None

    quantity = order.quantity
    if order.side == "buy":
        quantity = min(quantity, affordable_quantity(book.cash_usd, market_price, fee_pct))
        if quantity * market_price < min_trade_usd:
            return None

    now = datetime.now(timezone.utc)
    intent = OrderIntent(
        inst_id=pair,
        side=order.side,
        notional_usd=quantity * market_price,
        reference_price=signal.close,
        execution_price=market_price,
        reduce_only=order.side == "sell",
    )
    # Cost-basis notionals are a close enough proxy for limit checks here.
    account = AccountState(
        instrument_notional_usd={
            inst_id: float(row["quantity"]) * float(row["avg_entry_price"])
            for inst_id, row in state["book"].get("positions", {}).items()
        },
        total_exposure_usd=sum(
            float(row["quantity"]) * float(row["avg_entry_price"])
            for row in state["book"].get("positions", {}).values()
        ),
        daily_realized_pnl_usd=daily_realized_pnl_usd(state, now=now),
    )

    decision = risk_gate.validate(intent, account)
    if not decision.allowed:
        add_event(
            event="paper_trend_order_rejected",
            level="warning",
            pair=pair,
            strategy=STRATEGY_NAME,
            message=f"risk gate rejected paper {order.side}: {'; '.join(decision.rejection_reasons)}",
        )
        return None

    trade = apply_paper_fill(
        book,
        inst_id=pair,
        side=order.side,
        quantity=quantity,
        price=market_price,
        fee_pct=fee_pct,
    )
    trade["occurred_at"] = now.isoformat()
    trade["target_fraction"] = order.target_fraction
    trade["decision_price"] = signal.close

    execution_log.record(
        ExecutionRecord(
            inst_id=pair,
            side=order.side,
            quantity=quantity,
            decision_price=signal.close,
            fill_price=market_price,
            fee_usd=float(trade["fee_usd"]),
            occurred_at=now.isoformat(),
            strategy=STRATEGY_NAME,
        )
    )

    state["book"] = book.to_payload()
    state["trades"].append(trade)
    add_event(
        event="paper_trend_fill",
        pair=pair,
        strategy=STRATEGY_NAME,
        message=(
            f"paper {order.side} {quantity:.6f} {pair} @ {market_price:,.2f}"
            f" (target {order.target_fraction:.2f})"
        ),
        details=trade,
    )
    return trade


async def snapshot_equity(
    *,
    market_data: OKXPublicMarketData,
    state: dict[str, Any],
    pairs: Sequence[str],
) -> float:
    book = PaperBook.from_payload(state["book"])
    prices: dict[str, float] = {}
    for pair in pairs:
        ticker = await market_data.get_ticker(pair)
        prices[pair] = float(ticker["mid_price"] or ticker["last"])
    equity = book.equity_usd(prices)
    state["equity_history"].append(
        {"at": datetime.now(timezone.utc).isoformat(), "equity_usd": equity}
    )
    # Keep the state file bounded.
    state["equity_history"] = state["equity_history"][-2000:]
    return equity


# --------------------------------------------------------------------------- #
# Entrypoints
# --------------------------------------------------------------------------- #


async def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    pairs = parse_pairs(args.pairs)
    ma_periods = parse_ma_periods(args.ma_periods)
    market_data = OKXPublicMarketData()
    try:
        candles_by_inst = {
            pair: await fetch_daily_candles(market_data, pair, days=args.backtest_days)
            for pair in pairs
        }
    finally:
        await market_data.close()

    result = backtest_trend_following(
        candles_by_inst,
        ma_periods=ma_periods,
        allocation_usd_per_inst=args.allocation_usd,
        fee_pct_per_side=args.fee_pct,
        min_trade_usd=args.min_trade_usd,
    )
    result["candles_fetched"] = {pair: len(rows) for pair, rows in candles_by_inst.items()}
    return result


async def run_paper_loop(args: argparse.Namespace) -> dict[str, Any]:
    pairs = parse_pairs(args.pairs)
    ma_periods = parse_ma_periods(args.ma_periods)
    state_path = Path(args.state_file)
    state = load_state(state_path, pairs=pairs, allocation_usd=args.allocation_usd)

    risk_gate = build_risk_gate_from_settings(settings)
    execution_log = ExecutionQualityLog(settings.RISK_EXECUTION_LOG_FILE)
    market_data = OKXPublicMarketData()

    started_at = datetime.now(timezone.utc)
    add_event(
        event="paper_trend_started",
        strategy=STRATEGY_NAME,
        message=f"paper trend following started for {', '.join(pairs)}",
        details={
            "pairs": list(pairs),
            "ma_periods": list(ma_periods),
            "allocation_usd": args.allocation_usd,
            "fee_pct": args.fee_pct,
        },
    )

    fills = 0
    try:
        while True:
            for pair in pairs:
                try:
                    trade = await process_pair(
                        pair=pair,
                        market_data=market_data,
                        state=state,
                        risk_gate=risk_gate,
                        execution_log=execution_log,
                        ma_periods=ma_periods,
                        allocation_usd=args.allocation_usd,
                        fee_pct=args.fee_pct,
                        min_trade_usd=args.min_trade_usd,
                    )
                    if trade:
                        fills += 1
                except Exception as exc:  # keep the loop alive on transient errors
                    add_event(
                        event="paper_trend_error",
                        level="error",
                        pair=pair,
                        strategy=STRATEGY_NAME,
                        message=f"{type(exc).__name__}: {exc}",
                    )

            try:
                equity = await snapshot_equity(market_data=market_data, state=state, pairs=pairs)
                state["last_loop_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state_path, state)
                add_event(
                    event="paper_trend_status",
                    strategy=STRATEGY_NAME,
                    message=f"paper equity ${equity:,.2f} ({fills} fills so far)",
                    details={"equity_usd": equity, "fills": fills},
                )
            except Exception as exc:
                add_event(
                    event="paper_trend_error",
                    level="error",
                    strategy=STRATEGY_NAME,
                    message=f"status snapshot failed: {type(exc).__name__}: {exc}",
                )

            if args.duration_seconds > 0:
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                if elapsed >= args.duration_seconds:
                    break
            await asyncio.sleep(max(args.poll_seconds, 30))
    finally:
        save_state(state_path, state)
        await market_data.close()
        add_event(
            event="paper_trend_stopped",
            strategy=STRATEGY_NAME,
            message="paper trend following stopped",
            details={"fills": fills},
        )

    return {"fills": fills, "state_file": str(state_path)}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.backtest:
        result = asyncio.run(run_backtest(args))
    else:
        result = asyncio.run(run_paper_loop(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
