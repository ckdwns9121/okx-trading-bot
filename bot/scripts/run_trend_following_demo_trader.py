"""OKX DEMO trader for daily MA-ensemble trend following on BTC/ETH perps.

Sends REAL orders to the OKX demo-trading environment (simulated funds,
``OKX_MODE=demo`` enforced). Long/flat only at 1x leverage, so a perp
position behaves like holding spot. Every order passes the pre-trade
RiskGate, fills are recorded in the TCA log with the real average fill
price, and each cycle reconciles the bot's book against OKX positions.

Usage:
    python -m scripts.run_trend_following_demo_trader --once   # single pass
    python -m scripts.run_trend_following_demo_trader          # hourly loop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Sequence

from app.config import settings
from app.core.donchian import DonchianParams, decide as donchian_decide
from app.core.execution_quality import ExecutionQualityLog, ExecutionRecord
from app.core.indicators import atr_wilder
from app.core.reconciliation import reconcile_positions
from app.core.risk_gate import AccountState, OrderIntent, RiskGate, build_risk_gate_from_settings
from app.core.runtime_events import add_event
from app.core.trend_following import evaluate_trend
from app.exchange.okx_client import OKXClient
from app.exchange.public_market_data import OKXPublicMarketData
from scripts.run_trend_following_paper_trader import (
    daily_realized_pnl_usd,
    fetch_daily_candles,
    load_state,
    parse_ma_periods,
    save_state,
)

STRATEGY_NAME = "Daily MA Trend Following (OKX demo)"
DONCHIAN_STRATEGY_NAME = "Donchian Breakout (OKX demo)"
FILL_POLL_ATTEMPTS = 5
FILL_POLL_DELAY_SECONDS = 1.0


def strategy_label(strategy: str) -> str:
    return DONCHIAN_STRATEGY_NAME if strategy == "donchian" else STRATEGY_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default="BTC-USDT-SWAP,ETH-USDT-SWAP")
    parser.add_argument("--allocation-usd", type=float, default=1000.0, help="Target notional per pair.")
    parser.add_argument(
        "--leverage",
        type=int,
        default=1,
        help="Margin leverage. >1 amplifies drawdowns and invalidates the 1x backtest evidence.",
    )
    parser.add_argument(
        "--strategy",
        choices=("ma", "donchian"),
        default="ma",
        help="Signal engine: MA-ensemble fractions or Donchian channel breakout (all-in/all-out).",
    )
    parser.add_argument("--donchian-entry", type=int, default=55)
    parser.add_argument("--donchian-exit", type=int, default=20)
    parser.add_argument(
        "--donchian-atr-stop",
        type=float,
        default=2.0,
        help="ATR(20) multiple below entry that force-exits; 0 disables.",
    )
    parser.add_argument("--ma-periods", default="20,50,100")
    parser.add_argument("--min-trade-usd", type=float, default=50.0)
    parser.add_argument("--poll-seconds", type=int, default=3600)
    parser.add_argument("--duration-seconds", type=int, default=0, help="0 runs until interrupted.")
    parser.add_argument("--once", action="store_true", help="Run a single evaluation pass and exit.")
    parser.add_argument("--state-file", default="state/trend_following_demo.json")
    return parser


def parse_swap_pairs(raw: str) -> tuple[str, ...]:
    pairs = tuple(item.strip().upper() for item in raw.split(",") if item.strip())
    if not pairs:
        raise ValueError("at least one pair is required")
    for pair in pairs:
        if not pair.endswith("-SWAP"):
            raise ValueError(f"{pair}: demo trader trades OKX perpetuals (…-SWAP)")
    return pairs


# --------------------------------------------------------------------------- #
# Sizing (pure, unit-tested)
# --------------------------------------------------------------------------- #


def contracts_for_notional(
    *,
    notional_usd: float,
    price: float,
    ct_val: Decimal,
    lot_size: Decimal,
    min_size: Decimal,
) -> Decimal:
    """Contracts whose notional is closest to (but not above) the target."""

    if notional_usd <= 0.0 or price <= 0.0:
        return Decimal("0")
    raw = Decimal(str(notional_usd)) / (Decimal(str(price)) * ct_val)
    stepped = (raw / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size
    if stepped < min_size:
        return Decimal("0")
    return stepped


def contract_notional_usd(contracts: Decimal, price: float, ct_val: Decimal) -> float:
    return float(contracts * ct_val * Decimal(str(price)))


# --------------------------------------------------------------------------- #
# Exchange helpers
# --------------------------------------------------------------------------- #


async def fetch_instrument_specs(
    market_data: OKXPublicMarketData, pairs: Sequence[str]
) -> dict[str, dict[str, Decimal]]:
    specs: dict[str, dict[str, Decimal]] = {}
    for pair in pairs:
        rows = await market_data.get_instruments(inst_type="SWAP", inst_id=pair)
        if not rows:
            raise SystemExit(f"OKX has no instrument spec for {pair}")
        row = rows[0]
        specs[pair] = {
            "ct_val": Decimal(str(row.get("ctVal") or "0")),
            "lot_size": Decimal(str(row.get("lotSz") or "1")),
            "min_size": Decimal(str(row.get("minSz") or "1")),
        }
        if specs[pair]["ct_val"] <= 0:
            raise SystemExit(f"{pair}: invalid ctVal in instrument spec")
    return specs


async def exchange_position_contracts(client: OKXClient, pair: str) -> Decimal:
    """Net long contracts on the exchange for the pair (long/flat book)."""
    for row in await client.get_positions():
        if str(row.get("instId")) != pair:
            continue
        try:
            pos = Decimal(str(row.get("pos") or "0"))
        except ArithmeticError:
            continue
        if pos > 0:
            return pos
    return Decimal("0")


async def wait_for_fill(
    client: OKXClient, *, pair: str, cl_ord_id: str
) -> dict[str, Any] | None:
    for _ in range(FILL_POLL_ATTEMPTS):
        try:
            order = await client.get_order_by_cl_ord_id(cl_ord_id, pair)
        except Exception:
            order = {}
        state = str(order.get("state") or "")
        if state == "filled":
            return order
        if state in {"canceled", "mmp_canceled"}:
            return None
        await asyncio.sleep(FILL_POLL_DELAY_SECONDS)
    return None


# --------------------------------------------------------------------------- #
# One evaluation pass for one pair
# --------------------------------------------------------------------------- #


async def process_pair(
    *,
    pair: str,
    client: OKXClient,
    market_data: OKXPublicMarketData,
    state: dict[str, Any],
    risk_gate: RiskGate,
    execution_log: ExecutionQualityLog,
    spec: dict[str, Decimal],
    ma_periods: Sequence[int],
    allocation_usd: float,
    min_trade_usd: float,
    position_mode: str = "net_mode",
    leverage: int = 1,
    strategy: str = "ma",
    donchian_params: DonchianParams | None = None,
) -> dict[str, Any] | None:
    label = strategy_label(strategy)
    if strategy == "donchian":
        donchian_params = donchian_params or DonchianParams()
        min_history = donchian_params.warmup()
    else:
        min_history = max(ma_periods)
    candles = await fetch_daily_candles(market_data, pair, days=min_history + 5)
    if len(candles) <= min_history:
        add_event(
            event="demo_trend_skip",
            level="warning",
            pair=pair,
            strategy=label,
            message=f"not enough daily candles for {pair} ({len(candles)})",
        )
        return None

    latest_ts = str(candles[-1]["timestamp"])
    if state["processed_candle_ts"].get(pair) == latest_ts:
        return None

    closes = [float(row["close"]) for row in candles]
    state["processed_candle_ts"][pair] = latest_ts

    ticker = await market_data.get_ticker(pair)
    price = float(ticker["mid_price"] or ticker["last"])
    if price <= 0:
        return None

    current_contracts = await exchange_position_contracts(client, pair)
    current_notional = contract_notional_usd(current_contracts, price, spec["ct_val"])

    if strategy == "donchian":
        assert donchian_params is not None
        highs = [float(row["high"]) for row in candles]
        lows = [float(row["low"]) for row in candles]
        in_position = current_contracts > 0
        book_row = state.get("positions", {}).get(pair) or {}
        entry_price = float(book_row.get("avg_entry_price") or 0.0) or None
        entry_meta = state.setdefault("donchian_entry", {}).get(pair) or {}
        atr_series = atr_wilder(highs, lows, closes, donchian_params.atr_period)
        current_atr = atr_series[-1]
        atr_at_entry = float(entry_meta.get("atr") or 0.0) or (
            float(current_atr) if current_atr is not None else None
        )
        decision_signal = donchian_decide(
            highs=highs,
            lows=lows,
            closes=closes,
            in_position=in_position,
            entry_price=entry_price,
            atr_at_entry=atr_at_entry,
            params=donchian_params,
        )
        if decision_signal.action == "enter":
            target_fraction = 1.0
        elif decision_signal.action == "exit":
            target_fraction = 0.0
        else:
            target_fraction = 1.0 if in_position else 0.0
        decision_price = closes[-1]
        signal_message = (
            f"{pair} donchian {decision_signal.action} ({decision_signal.reason}),"
            f" close {closes[-1]:,.2f}"
        )
        signal_details: dict[str, Any] = {
            "action": decision_signal.action,
            "reason": decision_signal.reason,
            "prior_high": decision_signal.prior_high,
            "prior_low": decision_signal.prior_low,
            "target_fraction": target_fraction,
            "current_contracts": str(current_contracts),
        }
    else:
        signal = evaluate_trend(pair, closes, ma_periods=ma_periods)
        target_fraction = signal.target_fraction
        decision_price = signal.close
        signal_message = (
            f"{pair} votes {signal.votes}/{signal.total},"
            f" target ${target_fraction * allocation_usd:,.0f}, current ${current_notional:,.0f}"
        )
        signal_details = {
            "votes": signal.votes,
            "target_fraction": target_fraction,
            "current_contracts": str(current_contracts),
        }

    target_notional = target_fraction * allocation_usd
    delta = target_notional - current_notional

    add_event(
        event="demo_trend_signal",
        pair=pair,
        strategy=label,
        timeframe="1D",
        message=signal_message,
        details=signal_details,
    )

    if abs(delta) < min_trade_usd:
        return None

    side = "buy" if delta > 0 else "sell"
    contracts = contracts_for_notional(
        notional_usd=abs(delta),
        price=price,
        ct_val=spec["ct_val"],
        lot_size=spec["lot_size"],
        min_size=spec["min_size"],
    )
    if side == "sell":
        contracts = min(contracts, current_contracts)
    if contracts <= 0:
        return None
    order_notional = contract_notional_usd(contracts, price, spec["ct_val"])

    now = datetime.now(timezone.utc)
    intent = OrderIntent(
        inst_id=pair,
        side=side,
        notional_usd=order_notional,
        reference_price=decision_price,
        execution_price=price,
        reduce_only=side == "sell",
    )
    exposure_by_inst: dict[str, float] = {}
    for row in await client.get_positions():
        inst = str(row.get("instId") or "")
        try:
            notional = abs(float(row.get("notionalUsd") or 0.0))
        except (TypeError, ValueError):
            continue
        if inst and notional > 0.0:
            exposure_by_inst[inst] = exposure_by_inst.get(inst, 0.0) + notional
    account = AccountState(
        instrument_notional_usd=exposure_by_inst,
        total_exposure_usd=sum(exposure_by_inst.values()),
        daily_realized_pnl_usd=daily_realized_pnl_usd(state, now=now),
    )

    decision = risk_gate.validate(intent, account)
    if not decision.allowed:
        add_event(
            event="demo_trend_order_rejected",
            level="warning",
            pair=pair,
            strategy=label,
            message=f"risk gate rejected {side}: {'; '.join(decision.rejection_reasons)}",
        )
        return None

    cl_ord_id = uuid.uuid4().hex
    # In long/short mode both legs act on the long side (open long / close long)
    # and posSide replaces reduceOnly; in net mode reduceOnly marks the close.
    long_short = position_mode == "long_short_mode"
    await client.place_order(
        pair=pair,
        side=side,
        size=str(contracts),
        leverage=leverage,
        order_type="market",
        cl_ord_id=cl_ord_id,
        pos_side="long" if long_short else None,
        reduce_only=(side == "sell") and not long_short,
    )
    order = await wait_for_fill(client, pair=pair, cl_ord_id=cl_ord_id)
    if order is None:
        add_event(
            event="demo_trend_order_unfilled",
            level="error",
            pair=pair,
            strategy=label,
            message=f"{side} {contracts} {pair} not confirmed filled; check manually",
        )
        return None

    fill_price = float(order.get("avgPx") or price)
    filled_contracts = Decimal(str(order.get("accFillSz") or contracts))
    fee_usd = abs(float(order.get("fee") or 0.0))
    filled_notional = contract_notional_usd(filled_contracts, fill_price, spec["ct_val"])

    # Book-keeping for realized PnL (long/flat, average entry).
    book = state.setdefault("positions", {})
    row = book.setdefault(pair, {"contracts": "0", "avg_entry_price": 0.0})
    held = Decimal(str(row["contracts"]))
    realized: float | None = None
    if side == "buy":
        total_cost = float(row["avg_entry_price"]) * float(held) + fill_price * float(filled_contracts)
        held += filled_contracts
        row["avg_entry_price"] = total_cost / float(held) if held > 0 else 0.0
    else:
        realized = (
            (fill_price - float(row["avg_entry_price"]))
            * float(filled_contracts)
            * float(spec["ct_val"])
            - fee_usd
        )
        held = max(held - filled_contracts, Decimal("0"))
        if held == 0:
            row["avg_entry_price"] = 0.0
    row["contracts"] = str(held)

    if strategy == "donchian":
        entries = state.setdefault("donchian_entry", {})
        if side == "buy":
            atr_series = atr_wilder(
                [float(r["high"]) for r in candles],
                [float(r["low"]) for r in candles],
                closes,
                (donchian_params or DonchianParams()).atr_period,
            )
            last_atr = atr_series[-1]
            entries[pair] = {"atr": float(last_atr) if last_atr is not None else 0.0}
        elif held == 0:
            entries.pop(pair, None)

    trade = {
        "inst_id": pair,
        "side": side,
        "contracts": str(filled_contracts),
        "price": fill_price,
        "notional_usd": filled_notional,
        "fee_usd": fee_usd,
        "realized_pnl_usd": realized,
        "decision_price": decision_price,
        "target_fraction": target_fraction,
        "occurred_at": now.isoformat(),
        "cl_ord_id": cl_ord_id,
    }
    state["trades"].append(trade)

    execution_log.record(
        ExecutionRecord(
            inst_id=pair,
            side=side,
            quantity=float(filled_contracts * spec["ct_val"]),
            decision_price=decision_price,
            fill_price=fill_price,
            fee_usd=fee_usd,
            occurred_at=now.isoformat(),
            strategy=label,
            order_ref=cl_ord_id,
        )
    )
    add_event(
        event="demo_trend_fill",
        pair=pair,
        strategy=label,
        message=(
            f"demo {side} {filled_contracts} contracts {pair} @ {fill_price:,.2f}"
            f" (${filled_notional:,.0f}, target {target_fraction:.2f})"
        ),
        details=trade,
    )
    return trade


async def sync_book_from_exchange(
    *,
    client: OKXClient,
    state: dict[str, Any],
    pairs: Sequence[str],
) -> None:
    """Adopt exchange positions as the local book at startup.

    A fresh state file (first run, moved volume, manual demo trades) must not
    read as an incident: at boot the exchange IS the truth. Mid-loop drift is
    still treated as critical by reconcile_books.
    """

    book = state.setdefault("positions", {})
    exchange: dict[str, dict[str, Any]] = {}
    for row in await client.get_positions():
        inst = str(row.get("instId") or "")
        if inst not in pairs:
            continue
        try:
            pos = Decimal(str(row.get("pos") or "0"))
            avg_px = float(row.get("avgPx") or 0.0)
        except (ArithmeticError, TypeError, ValueError):
            continue
        if pos > 0:
            exchange[inst] = {"contracts": str(pos), "avg_entry_price": avg_px}

    before = {
        pair: row
        for pair, row in book.items()
        if Decimal(str(row.get("contracts") or "0")) > 0
    }
    if before == exchange:
        return

    for pair in list(book):
        if pair not in exchange:
            book.pop(pair)
    book.update(exchange)
    add_event(
        event="demo_trend_book_synced",
        level="warning",
        strategy=STRATEGY_NAME,
        message=f"local book adopted exchange positions at startup: {sorted(exchange) or 'flat'}",
        details={"before": before, "after": exchange},
    )


async def reconcile_books(
    *,
    client: OKXClient,
    state: dict[str, Any],
    risk_gate: RiskGate,
) -> None:
    local = [
        {"inst_id": pair, "direction": "long", "quantity": float(Decimal(str(row["contracts"])))}
        for pair, row in state.get("positions", {}).items()
        if Decimal(str(row.get("contracts") or "0")) > 0
    ]
    exchange_rows = await client.get_positions()
    report = reconcile_positions(local, exchange_rows, size_tolerance_pct=0.5)
    if report.ok:
        return
    level = "error" if report.critical else "warning"
    add_event(
        event="demo_trend_reconciliation_mismatch",
        level=level,
        strategy=STRATEGY_NAME,
        message=f"reconciliation found {len(report.discrepancies)} discrepancies",
        details=report.to_payload(),
    )
    if report.critical:
        risk_gate.kill_switch.trip(
            reason="demo trend trader reconciliation mismatch",
            source="reconciliation",
        )


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if settings.OKX_MODE != "demo":
        raise SystemExit(
            f"refusing to run: OKX_MODE={settings.OKX_MODE!r}; this trader is demo-only"
        )

    pairs = parse_swap_pairs(args.pairs)
    ma_periods = parse_ma_periods(args.ma_periods)
    donchian_params = DonchianParams(
        entry_period=args.donchian_entry,
        exit_period=args.donchian_exit,
        atr_period=20,
        atr_stop_mult=args.donchian_atr_stop if args.donchian_atr_stop > 0 else None,
    )
    label = strategy_label(args.strategy)
    state_path = Path(args.state_file)
    state = load_state(state_path, pairs=pairs, allocation_usd=args.allocation_usd)
    state.setdefault("positions", {})
    # Record what this process is actually running so the API/UI can show it
    # without guessing from CLI flags or compose files.
    state["strategy"] = label
    state["config"] = {
        "strategy": args.strategy,
        "pairs": list(pairs),
        "allocation_usd": args.allocation_usd,
        "leverage": args.leverage,
        "poll_seconds": args.poll_seconds,
        "min_trade_usd": args.min_trade_usd,
        "ma_periods": list(ma_periods),
        "donchian": {
            "entry_period": donchian_params.entry_period,
            "exit_period": donchian_params.exit_period,
            "atr_period": donchian_params.atr_period,
            "atr_stop_mult": donchian_params.atr_stop_mult,
        },
        "mode": settings.OKX_MODE,
    }

    risk_gate = build_risk_gate_from_settings(settings)
    execution_log = ExecutionQualityLog(settings.RISK_EXECUTION_LOG_FILE)
    market_data = OKXPublicMarketData()
    client = OKXClient(
        api_key=settings.OKX_API_KEY,
        secret=settings.OKX_SECRET,
        passphrase=settings.OKX_PASSPHRASE,
        mode=settings.OKX_MODE,
    )

    # Persist runtime events to the DB so the dashboard log page sees this
    # process. Logging must never block trading, so failures are tolerated.
    persistence_enabled = False
    try:
        from app.core.runtime_events import configure_persistence

        from app.db.database import AsyncSessionLocal

        configure_persistence(session_factory=AsyncSessionLocal)
        persistence_enabled = True
    except Exception as exc:
        add_event(
            event="demo_trend_persistence_warning",
            level="warning",
            strategy=STRATEGY_NAME,
            message=f"runtime event DB persistence unavailable: {exc}",
        )

    fills = 0
    started_at = datetime.now(timezone.utc)
    try:
        specs = await fetch_instrument_specs(market_data, pairs)
        try:
            position_mode = await client.get_position_mode()
        except Exception as exc:
            position_mode = "net_mode"
            add_event(
                event="demo_trend_position_mode_warning",
                level="warning",
                strategy=STRATEGY_NAME,
                message=f"could not read position mode, assuming net_mode: {exc}",
            )
        if args.leverage != 1:
            add_event(
                event="demo_trend_leverage_notice",
                level="warning",
                strategy=STRATEGY_NAME,
                message=(
                    f"running at {args.leverage}x leverage: drawdowns scale accordingly and"
                    " results no longer validate the 1x strategy evidence"
                ),
            )
        for pair in pairs:
            try:
                await client.set_leverage(pair, args.leverage)
            except Exception as exc:
                add_event(
                    event="demo_trend_leverage_warning",
                    level="warning",
                    pair=pair,
                    strategy=STRATEGY_NAME,
                    message=f"set_leverage failed: {exc}",
                )

        add_event(
            event="demo_trend_started",
            strategy=label,
            message=f"OKX demo trader started for {', '.join(pairs)} (strategy={args.strategy})",
            details={
                "pairs": list(pairs),
                "strategy": args.strategy,
                "ma_periods": list(ma_periods),
                "donchian": {
                    "entry_period": donchian_params.entry_period,
                    "exit_period": donchian_params.exit_period,
                    "atr_stop_mult": donchian_params.atr_stop_mult,
                },
                "allocation_usd": args.allocation_usd,
                "mode": settings.OKX_MODE,
            },
        )
        await sync_book_from_exchange(client=client, state=state, pairs=pairs)

        while True:
            for pair in pairs:
                try:
                    trade = await process_pair(
                        pair=pair,
                        client=client,
                        market_data=market_data,
                        state=state,
                        risk_gate=risk_gate,
                        execution_log=execution_log,
                        spec=specs[pair],
                        ma_periods=ma_periods,
                        allocation_usd=args.allocation_usd,
                        min_trade_usd=args.min_trade_usd,
                        position_mode=position_mode,
                        leverage=args.leverage,
                        strategy=args.strategy,
                        donchian_params=donchian_params,
                    )
                    if trade:
                        fills += 1
                except Exception as exc:
                    add_event(
                        event="demo_trend_error",
                        level="error",
                        pair=pair,
                        strategy=STRATEGY_NAME,
                        message=f"{type(exc).__name__}: {exc}",
                    )

            try:
                await reconcile_books(client=client, state=state, risk_gate=risk_gate)
            except Exception as exc:
                add_event(
                    event="demo_trend_error",
                    level="error",
                    strategy=STRATEGY_NAME,
                    message=f"reconciliation failed: {type(exc).__name__}: {exc}",
                )

            state["last_loop_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state_path, state)

            if args.once:
                break
            if args.duration_seconds > 0:
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                if elapsed >= args.duration_seconds:
                    break
            await asyncio.sleep(max(args.poll_seconds, 30))
    finally:
        save_state(state_path, state)
        await market_data.close()
        await client.close()
        add_event(
            event="demo_trend_stopped",
            strategy=STRATEGY_NAME,
            message="OKX demo trend trader stopped",
            details={"fills": fills},
        )
        if persistence_enabled:
            try:
                from app.core.runtime_events import shutdown_persistence

                # Give the queue a moment to drain the final events.
                await asyncio.sleep(1.0)
                await shutdown_persistence()
            except Exception:
                pass

    return {"fills": fills, "state_file": str(state_path), "kill_switch": risk_gate.kill_switch.status()}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
