"""Compare candidate strategies on real OKX data with one cost-aware harness.

Runs the incumbent MA-ensemble baseline plus the researched community
candidates (Donchian breakout, volatility breakout, BbandRsi mean reversion)
over identical windows, fees included, no look-ahead. Read-only: fetches
public candles, places no orders.

Usage:
    python -m scripts.run_strategy_backtests --days 900
    python -m scripts.run_strategy_backtests --days 400 --pairs BTC-USDT,ETH-USDT
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Sequence

from app.core.bband_rsi import BbandRsiParams, backtest_bband_rsi
from app.core.donchian import DonchianParams, backtest_donchian
from app.core.trend_following import backtest_trend_following
from app.core.volatility_breakout import (
    VolatilityBreakoutParams,
    backtest_volatility_breakout,
)
from app.exchange.public_market_data import OKXPublicMarketData
from scripts.run_trend_following_paper_trader import fetch_candles, parse_pairs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default="BTC-USDT,ETH-USDT")
    parser.add_argument("--days", type=int, default=900)
    parser.add_argument("--allocation-usd", type=float, default=1000.0)
    parser.add_argument("--fee-pct", type=float, default=0.10)
    parser.add_argument("--json", action="store_true", help="emit raw JSON only")
    return parser


async def gather_data(
    pairs: Sequence[str], days: int
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    market = OKXPublicMarketData()
    try:
        daily: dict[str, list[dict[str, Any]]] = {}
        hourly: dict[str, list[dict[str, Any]]] = {}
        for pair in pairs:
            daily[pair] = await fetch_candles(market, pair, count=days, bar="1D")
            hourly[pair] = await fetch_candles(market, pair, count=days * 24, bar="1H")
        return daily, hourly
    finally:
        await market.close()


def run_all(
    daily: dict[str, list[dict[str, Any]]],
    hourly: dict[str, list[dict[str, Any]]],
    *,
    allocation_usd: float,
    fee_pct: float,
) -> list[dict[str, Any]]:
    common = {"allocation_usd_per_inst": allocation_usd, "fee_pct_per_side": fee_pct}
    results: list[dict[str, Any]] = []

    baseline = backtest_trend_following(daily, **common)
    baseline["strategy"] = "ma_ensemble_baseline"
    results.append(baseline)

    results.append(
        backtest_donchian(daily, params=DonchianParams(20, 10, 20, 2.0), **common)
    )
    results.append(
        backtest_donchian(daily, params=DonchianParams(55, 20, 20, 2.0), **common)
    )
    results.append(
        backtest_volatility_breakout(
            hourly, params=VolatilityBreakoutParams(k=0.5, use_ma_filter=True), **common
        )
    )
    results.append(
        backtest_volatility_breakout(
            hourly, params=VolatilityBreakoutParams(k=0.5, use_ma_filter=False), **common
        )
    )
    results.append(backtest_bband_rsi(hourly, params=BbandRsiParams(), **common))
    return results


def format_table(results: list[dict[str, Any]]) -> str:
    headers = ["strategy", "params", "return%", "maxDD%", "trades", "win%", "fees$"]
    rows = []
    for res in results:
        params = res.get("params") or {}
        label = ",".join(f"{key}={value}" for key, value in params.items()) or "-"
        rows.append(
            [
                res["strategy"],
                label[:44],
                f"{res['total_return_pct']:+.1f}",
                f"{res['max_drawdown_pct']:.1f}",
                str(res["trade_count"]),
                f"{res.get('win_rate_pct', 0.0):.0f}",
                f"{res['fees_paid_usd']:.0f}",
            ]
        )
    widths = [max(len(row[col]) for row in [headers, *rows]) for col in range(len(headers))]
    lines = ["  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)) for row in [headers, *rows]]
    lines.insert(1, "-" * len(lines[0]))
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    pairs = parse_pairs(args.pairs)
    daily, hourly = await gather_data(pairs, args.days)
    results = run_all(
        daily, hourly, allocation_usd=args.allocation_usd, fee_pct=args.fee_pct
    )
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        buy_hold = results[0].get("buy_hold_return_pct")
        print(f"pairs={','.join(pairs)} days={args.days} fee={args.fee_pct}%/side")
        if buy_hold is not None:
            print(
                f"buy&hold benchmark: {buy_hold:+.1f}% "
                f"(maxDD {results[0].get('buy_hold_max_drawdown_pct', 0.0):.1f}%)\n"
            )
        print(format_table(results))
    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
