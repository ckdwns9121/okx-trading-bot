#!/usr/bin/env python3
"""Run an in-memory OKX-public-data validation for the ma_7d_5m strategy.

This script deliberately avoids DB writes and live/demo order endpoints. It only
fetches market candles and reuses the project backtest simulator in memory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import logging

import structlog

BOT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BOT_DIR.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from app.config import settings  # noqa: E402
from app.core.backtest_engine import _compute_metrics, _simulate_sync  # noqa: E402
from app.core.strategy_base import Signal, TradeSignal, TradingContext  # noqa: E402
from app.exchange.okx_client import OKXClient  # noqa: E402
from strategies.ma_7d_5m import SevenDayMA5mStrategy  # noqa: E402

_MS_PER_SECOND = 1000
DEFAULT_PAIRS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")
DEFAULT_SCENARIOS: dict[str, dict[str, Any]] = {
    "default_long": {},
    "limited_long": {"risk_profile": "limited"},
    "limited_both": {"risk_profile": "limited", "direction_mode": "both"},
}


def configure_script_logging(*, verbose: bool) -> None:
    """Keep validation runs quiet unless explicitly debugging."""
    if verbose:
        return
    logging.basicConfig(level=logging.WARNING)
    structlog.configure(
        processors=[structlog.stdlib.filter_by_level],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


@dataclass(frozen=True)
class CandleView:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _ms_to_dt(ms: str | int) -> datetime:
    return datetime.fromtimestamp(int(ms) / _MS_PER_SECOND, tz=timezone.utc).replace(tzinfo=None)


def _candle_dict(candle: CandleView) -> dict[str, Any]:
    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


async def fetch_window(
    client: OKXClient,
    *,
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[CandleView]:
    """Fetch candles from OKX, walking backwards from end to start."""
    start_ms = int(start.replace(tzinfo=timezone.utc).timestamp() * _MS_PER_SECOND)
    end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * _MS_PER_SECOND)
    cursor_after: str | None = str(end_ms + 1)
    by_ts: dict[int, CandleView] = {}

    while True:
        page = await client.get_candles(pair=pair, timeframe=timeframe, limit=100, after=cursor_after)
        if not page:
            break

        for raw in page:
            ts_ms = int(raw["timestamp"])
            if start_ms <= ts_ms <= end_ms:
                by_ts[ts_ms] = CandleView(
                    timestamp=_ms_to_dt(ts_ms),
                    open=float(raw["open"]),
                    high=float(raw["high"]),
                    low=float(raw["low"]),
                    close=float(raw["close"]),
                    volume=float(raw["volume"]),
                )

        oldest_in_page = int(page[-1]["timestamp"])
        if oldest_in_page <= start_ms:
            break
        next_cursor = str(oldest_in_page)
        if next_cursor == cursor_after:
            break
        cursor_after = next_cursor

    return [by_ts[ts] for ts in sorted(by_ts)]


async def run_strategy(
    candles: list[CandleView],
    *,
    pair: str,
    timeframe: str,
    parameters: dict[str, Any],
    initial_balance: float,
    leverage: int,
    fee_rate: float,
    slippage_pct: float,
    cooldown_candles: int,
    funding_rate_per_8h: float,
    liquidity_impact_factor: float,
    maintenance_margin_ratio: float,
    liquidation_fee_pct: float,
) -> dict[str, Any]:
    strategy = SevenDayMA5mStrategy()
    strategy.configure(parameters)
    await strategy.on_start()

    history: list[dict[str, Any]] = []
    signals: list[TradeSignal] = []
    sim_balance = initial_balance
    sim_position: dict[str, Any] | None = None
    lookback = strategy.lookback_period

    for candle in candles:
        ctx = TradingContext(
            current_position=sim_position,
            account_balance=sim_balance,
            leverage=leverage,
            pair=pair,
        )
        try:
            signal = await strategy.on_candle(_candle_dict(candle), history[-lookback:], ctx)
        except Exception:
            signal = TradeSignal(signal=Signal.HOLD, pair=pair, leverage=leverage)
        signals.append(signal)

        if signal.signal in (Signal.LONG, Signal.SHORT):
            new_dir = "buy" if signal.signal == Signal.LONG else "sell"
            if sim_position is None or sim_position.get("direction") != new_dir:
                sim_position = {
                    "direction": new_dir,
                    "entry_price": candle.close,
                    "quantity": sim_balance * (signal.size_pct / 100.0),
                    "unrealized_pnl": 0.0,
                }
        elif signal.signal == Signal.CLOSE:
            sim_position = None

        history.append(_candle_dict(candle))

    await strategy.on_stop()

    trades, balance_series, final_balance = await asyncio.to_thread(
        _simulate_sync,
        candles,
        strategy.lookback_period,
        timeframe,
        initial_balance,
        leverage,
        fee_rate,
        slippage_pct,
        signals,
        0.03,
        cooldown_candles,
        funding_rate_per_8h,
        liquidity_impact_factor,
        maintenance_margin_ratio,
        liquidation_fee_pct,
    )
    total_pnl, win_rate, max_drawdown, sharpe_ratio = _compute_metrics(
        trades,
        initial_balance,
        balance_series,
    )
    return {
        "run_id": str(uuid.uuid4()),
        "parameters": parameters,
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "total_pnl": total_pnl,
        "return_pct": (total_pnl / initial_balance) * 100.0,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": len(trades),
        "long_trades": sum(1 for trade in trades if trade.direction == "buy"),
        "short_trades": sum(1 for trade in trades if trade.direction == "sell"),
    }


def _build_windows(end: datetime, days: int, count: int) -> list[tuple[str, datetime, datetime]]:
    windows: list[tuple[str, datetime, datetime]] = []
    cursor_end = end
    for idx in range(count):
        start = cursor_end - timedelta(days=days)
        label = "recent" if idx == 0 else f"prior_{idx}"
        windows.append((label, start, cursor_end))
        cursor_end = start
    return windows


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# MA 7D 5m Validation Report",
        "",
        f"작성일: {payload['created_at']}",
        "",
        "## 목적",
        "",
        "`ma_7d_5m` 전략을 실거래/데모 시작 전에 최근 OKX 5분봉으로 독립 검증했다. 이 검증은 주문을 내지 않고 public candle만 가져와 인메모리 백테스트로 실행한다.",
        "",
        "## 설정",
        "",
        f"- Pairs: {', '.join(payload['pairs'])}",
        f"- Timeframe: {payload['timeframe']}",
        f"- Window days: {payload['window_days']} × {payload['window_count']} windows",
        f"- Initial balance: {payload['assumptions']['initial_balance']}",
        f"- Leverage: {payload['assumptions']['leverage']}",
        f"- Fee rate: {payload['assumptions']['fee_rate']}",
        f"- Slippage pct: {payload['assumptions']['slippage_pct']}",
        "",
        "## 결과",
        "",
        "| Window | Pair | Scenario | Candles | Trades | PnL | Return | Win | Max DD | Sharpe | Long/Short |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["results"]:
        if row["status"] != "ok":
            lines.append(
                f"| {row['window']} | {row['pair']} | {row['scenario']} | {row.get('candles', 0)} | - | ERROR | - | - | - | - | - |"
            )
            continue
        lines.append(
            "| {window} | {pair} | {scenario} | {candles} | {trade_count} | {pnl:.2f} | {ret:.2f}% | {win:.1f}% | {dd:.2f}% | {sharpe:.2f} | {long}/{short} |".format(
                window=row["window"],
                pair=row["pair"],
                scenario=row["scenario"],
                candles=row["candles"],
                trade_count=row["trade_count"],
                pnl=row["total_pnl"],
                ret=row["return_pct"],
                win=row["win_rate"] * 100.0,
                dd=row["max_drawdown"] * 100.0,
                sharpe=row["sharpe_ratio"],
                long=row["long_trades"],
                short=row["short_trades"],
            )
        )

    ok_rows = [row for row in payload["results"] if row["status"] == "ok"]
    positive = sum(1 for row in ok_rows if row["total_pnl"] > 0)
    max_dd = max((row["max_drawdown"] for row in ok_rows), default=0.0)
    best = max(ok_rows, key=lambda row: row["total_pnl"], default=None)
    median_like = sorted(ok_rows, key=lambda row: row["total_pnl"])[len(ok_rows) // 2] if ok_rows else None

    lines += [
        "",
        "## 판정",
        "",
        f"- Positive runs: {positive}/{len(ok_rows)}",
        f"- Worst max DD: {max_dd * 100.0:.2f}%",
    ]
    if best:
        lines.append(
            f"- Best raw PnL: {best['scenario']} / {best['pair']} / {best['window']} = {best['total_pnl']:.2f}"
        )
    if median_like:
        lines.append(
            f"- Median-like PnL row: {median_like['scenario']} / {median_like['pair']} / {median_like['window']} = {median_like['total_pnl']:.2f}"
        )

    if not ok_rows or positive < max(1, len(ok_rows) // 2) or max_dd > 0.25:
        lines.append("- 결론: **demo 후보 탈락/보류**. 수익 일관성 또는 DD 조건을 통과하지 못했다.")
    else:
        lines.append("- 결론: **추가 paper 후보 가능**. 단, 기존 `rsi_bollinger_regime` limited보다 우선하지는 않는다.")

    lines += [
        "",
        "## 다음 단계",
        "",
        "1. 이 전략은 통과 전까지 OKX demo 자동 실행 목록에 넣지 않는다.",
        "2. 개선한다면 파라미터 최적화보다 시장 레짐/거래 시간 필터를 먼저 검증한다.",
        "3. demo 후보는 기존 `rsi_bollinger_regime` limited를 유지한다.",
    ]
    return "\n".join(lines) + "\n"


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    end = _parse_dt(args.end) if args.end else datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    pairs = [pair.strip() for pair in args.pairs.split(",") if pair.strip()]
    windows = _build_windows(end, args.window_days, args.window_count)
    assumptions = {
        "initial_balance": args.initial_balance,
        "leverage": args.leverage,
        "fee_rate": args.fee_rate,
        "slippage_pct": args.slippage_pct,
        "cooldown_candles": args.cooldown_candles,
        "funding_rate_per_8h": args.funding_rate_per_8h,
        "liquidity_impact_factor": args.liquidity_impact_factor,
        "maintenance_margin_ratio": args.maintenance_margin_ratio,
        "liquidation_fee_pct": args.liquidation_fee_pct,
    }

    client = OKXClient(
        api_key=settings.OKX_API_KEY,
        secret=settings.OKX_SECRET,
        passphrase=settings.OKX_PASSPHRASE,
        mode=settings.OKX_MODE,
    )
    results: list[dict[str, Any]] = []
    try:
        for window_label, start, window_end in windows:
            for pair in pairs:
                candles = await fetch_window(client, pair=pair, timeframe=args.timeframe, start=start, end=window_end)
                for scenario, parameters in DEFAULT_SCENARIOS.items():
                    row_base = {
                        "window": window_label,
                        "start": start.isoformat(),
                        "end": window_end.isoformat(),
                        "pair": pair,
                        "timeframe": args.timeframe,
                        "scenario": scenario,
                        "candles": len(candles),
                    }
                    if len(candles) < SevenDayMA5mStrategy().lookback_period + 1:
                        results.append({**row_base, "status": "insufficient_candles"})
                        continue
                    metrics = await run_strategy(
                        candles,
                        pair=pair,
                        timeframe=args.timeframe,
                        parameters=parameters,
                        **assumptions,
                    )
                    results.append({**row_base, "status": "ok", **metrics})
    finally:
        await client.close()

    return {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "strategy": "ma_7d_5m",
        "pairs": pairs,
        "timeframe": args.timeframe,
        "window_days": args.window_days,
        "window_count": args.window_count,
        "assumptions": assumptions,
        "results": results,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--end", default=None, help="UTC ISO timestamp, e.g. 2026-05-08T12:00:00Z")
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument("--window-count", type=int, default=2)
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--leverage", type=int, default=2)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--cooldown-candles", type=int, default=3)
    parser.add_argument("--funding-rate-per-8h", type=float, default=0.0001)
    parser.add_argument("--liquidity-impact-factor", type=float, default=0.1)
    parser.add_argument("--maintenance-margin-ratio", type=float, default=0.005)
    parser.add_argument("--liquidation-fee-pct", type=float, default=0.002)
    parser.add_argument("--json-out", default=str(REPO_DIR / ".omx/context/ma-7d-5m-validation-results.json"))
    parser.add_argument("--md-out", default=str(REPO_DIR / "docs/ma-7d-5m-validation-report.md"))
    parser.add_argument("--verbose", action="store_true", help="Show strategy/API debug logs")
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_script_logging(verbose=args.verbose)

    payload = asyncio.run(_run(args))
    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    md_path = Path(args.md_out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_markdown_report(payload), encoding="utf-8")

    print(json.dumps({"json_out": str(json_path), "md_out": str(md_path), "results": len(payload["results"])}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
