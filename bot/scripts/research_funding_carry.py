"""Research: funding-rate carry (spot long + perp short) on OKX, cost-aware.

Read-only. Fetches public hourly candles (spot + perp) and the funding-rate
history OKX exposes (~3 months), then:

1. Applies OKX's published funding formula (Apr-2025 revision) to the hourly
   perp/spot basis as a premium-index proxy, and reports how well that
   reproduces the real funding OKX exposes (R²/RMSE), so the reader can judge
   whether extending the series further back is honest.
2. Simulates the carry rule on the full window (real funding where available,
   proxy before that): enter when the trailing average funding is extreme,
   hold while funding stays above the exit floor, pay every fee and the basis
   change on both legs.

Usage:
    python -m scripts.research_funding_carry --days 730 --pairs BTC,ETH,SOL,DOGE
    python -m scripts.research_funding_carry --days 730 --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.exchange.public_market_data import OKXPublicMarketData

HOUR_MS = 3_600_000
FUNDING_INTERVAL_MS = 8 * HOUR_MS
MAX_CANDLES_PER_REQUEST = 100
FUNDING_CLAMP = 0.0075  # OKX clamps funding to ±0.75% per interval


# --------------------------------------------------------------------------- #
# Data fetch (I/O)
# --------------------------------------------------------------------------- #


async def fetch_candles(market: OKXPublicMarketData, inst: str, *, count: int, bar: str) -> list[dict[str, Any]]:
    collected: dict[str, dict[str, Any]] = {}
    after: str | None = None
    while len(collected) < count:
        rows = await market.get_candles(inst, bar, limit=MAX_CANDLES_PER_REQUEST, after=after)
        if not rows:
            break
        for row in rows:
            if str(row.get("confirm", "1")) == "1":
                collected[str(row["timestamp"])] = row
        oldest = min(rows, key=lambda r: int(r["timestamp"]))
        nxt = str(oldest["timestamp"])
        if nxt == after:
            break
        after = nxt
    ordered = sorted(collected.values(), key=lambda r: int(r["timestamp"]))
    return ordered[-count:]


async def fetch_all_funding(market: OKXPublicMarketData, swap: str) -> list[dict[str, Any]]:
    out: dict[int, float] = {}
    after: str | None = None
    for _ in range(100):
        rows = await market.get_funding_rate_history(swap, limit=100, after=after)
        if not rows:
            break
        for r in rows:
            out[int(r["funding_time"])] = float(r.get("realized_rate") or r.get("funding_rate") or 0.0)
        oldest = str(min(int(r["funding_time"]) for r in rows))
        if oldest == after:
            break
        after = oldest
    return [{"ts": ts, "rate": rate} for ts, rate in sorted(out.items())]


async def load_dataset(pairs: Sequence[str], days: int, cache_dir: Path) -> dict[str, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    market = OKXPublicMarketData()
    data: dict[str, dict[str, Any]] = {}
    try:
        for base in pairs:
            spot, swap = f"{base}-USDT", f"{base}-USDT-SWAP"
            cache = cache_dir / f"carry_{base}_{days}d.json"
            if cache.exists():
                data[base] = json.loads(cache.read_text())
                continue
            spot_rows = await fetch_candles(market, spot, count=days * 24, bar="1H")
            perp_rows = await fetch_candles(market, swap, count=days * 24, bar="1H")
            funding = await fetch_all_funding(market, swap)
            data[base] = {
                "spot": [{"ts": int(r["timestamp"]), "close": float(r["close"])} for r in spot_rows],
                "perp": [{"ts": int(r["timestamp"]), "close": float(r["close"])} for r in perp_rows],
                "funding": funding,
            }
            cache.write_text(json.dumps(data[base]))
    finally:
        await market.close()
    return data


# --------------------------------------------------------------------------- #
# Pure analysis
# --------------------------------------------------------------------------- #


def hourly_basis(spot: list[dict[str, Any]], perp: list[dict[str, Any]]) -> dict[int, float]:
    """basis = perp/spot − 1 per hour, only where both candles exist."""
    spot_by_ts = {r["ts"]: r["close"] for r in spot}
    out: dict[int, float] = {}
    for r in perp:
        s = spot_by_ts.get(r["ts"])
        if s and s > 0:
            out[r["ts"]] = r["close"] / s - 1.0
    return out


def window_mean_basis(basis: dict[int, float], settle_ts: int) -> float | None:
    vals = [basis[t] for t in range(settle_ts - FUNDING_INTERVAL_MS + HOUR_MS, settle_ts + HOUR_MS, HOUR_MS) if t in basis]
    return statistics.fmean(vals) if len(vals) >= 6 else None


@dataclass
class Calibration:
    """How well the OKX formula applied to candle basis reproduces real funding."""

    r2: float
    rmse: float
    n: int
    share_real_at_base: float  # how often real funding sat exactly on the 0.01% base
    share_pred_at_base: float


INTEREST_8H = 0.0001  # 0.03% / 3 settlements per day
PREMIUM_CLAMP = 0.0005  # ±0.05% band around the interest rate


def okx_funding_from_premium(avg_premium: float) -> float:
    """OKX funding formula (April 2025 revision), before the per-instrument cap:
    clamp(avg_premium + clamp(interest − avg_premium, −0.05%, +0.05%), cap, floor).
    For −0.04% ≤ premium ≤ +0.06% this collapses to exactly 0.01%."""
    adj = max(-PREMIUM_CLAMP, min(PREMIUM_CLAMP, INTEREST_8H - avg_premium))
    return max(-FUNDING_CLAMP, min(FUNDING_CLAMP, avg_premium + adj))


def calibrate(basis: dict[int, float], funding: list[dict[str, Any]]) -> Calibration | None:
    xs, ys = [], []
    for row in funding:
        x = window_mean_basis(basis, row["ts"])
        if x is None:
            continue
        xs.append(okx_funding_from_premium(x))
        ys.append(row["rate"])
    if len(xs) < 30:
        return None
    my = statistics.fmean(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, xs))
    ss_tot = sum((y - my) ** 2 for y in ys)
    at = lambda v: abs(v - INTEREST_8H) < 1e-9
    return Calibration(
        r2=1.0 - ss_res / ss_tot if ss_tot else 0.0,
        rmse=math.sqrt(ss_res / len(xs)),
        n=len(xs),
        share_real_at_base=sum(1 for y in ys if at(y)) / len(ys),
        share_pred_at_base=sum(1 for x in xs if at(x)) / len(xs),
    )


def build_funding_series(
    basis: dict[int, float], funding: list[dict[str, Any]], calib: Calibration
) -> list[dict[str, Any]]:
    """8h settlement series over the whole candle window: real where OKX has it, proxy before."""
    real = {row["ts"]: row["rate"] for row in funding}
    if not basis:
        return []
    first, last = min(basis), max(basis)
    # settlements happen at 00/08/16 UTC
    start = (first // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
    series = []
    ts = start
    while ts <= last:
        if ts in real:
            series.append({"ts": ts, "rate": real[ts], "source": "real"})
        else:
            x = window_mean_basis(basis, ts)
            if x is not None:
                series.append({"ts": ts, "rate": okx_funding_from_premium(x), "source": "proxy"})
        ts += FUNDING_INTERVAL_MS
    return series


@dataclass(frozen=True)
class CarryParams:
    entry_rate: float  # per-8h funding needed to enter (e.g. 0.0003 = 0.03%)
    exit_rate: float  # leave when trailing avg falls below this
    lookback: int = 3  # settlements averaged for the signal
    notional_usd: float = 10_000.0
    spot_fee_pct: float = 0.10  # taker, per side
    perp_fee_pct: float = 0.05  # taker, per side
    spread_cost_pct: float = 0.02  # half-spread paid on each of the 4 fills, summed
    perp_margin_fraction: float = 0.5  # margin parked for the short leg (2x)


@dataclass
class CarryResult:
    params: dict[str, Any]
    round_trips: int
    settlements_in_position: int
    settlements_total: int
    time_in_market_pct: float
    funding_collected_usd: float
    basis_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float
    capital_usd: float
    net_return_pct: float
    annualized_return_pct: float
    worst_trade_usd: float
    best_trade_usd: float
    win_rate_pct: float
    years: float


def simulate_carry(series: list[dict[str, Any]], basis: dict[int, float], params: CarryParams) -> CarryResult:
    n = params.notional_usd
    round_trip_fee = n * 2 * (params.spot_fee_pct + params.perp_fee_pct) / 100.0 + n * params.spread_cost_pct * 4 / 100.0
    capital = n + n * params.perp_margin_fraction

    in_pos = False
    entry_basis = 0.0
    trade_pnl = 0.0
    trades: list[float] = []
    funding_total = basis_total = fees_total = 0.0
    in_count = 0

    for i, row in enumerate(series):
        signal = statistics.fmean(r["rate"] for r in series[max(0, i - params.lookback + 1) : i + 1])
        ts = row["ts"]
        b_now = basis.get(ts)
        if in_pos:
            got = row["rate"] * n
            funding_total += got
            trade_pnl += got
            in_count += 1
            if signal < params.exit_rate and b_now is not None:
                # cover perp short: gain if premium shrank since entry
                bpnl = (entry_basis - b_now) * n
                basis_total += bpnl
                fees_total += round_trip_fee / 2
                trade_pnl += bpnl - round_trip_fee / 2
                trades.append(trade_pnl)
                in_pos = False
        else:
            if signal >= params.entry_rate and b_now is not None:
                in_pos = True
                entry_basis = b_now
                fees_total += round_trip_fee / 2
                trade_pnl = -round_trip_fee / 2

    if in_pos and series:
        # mark the open trade to the last known basis
        b_last = basis.get(series[-1]["ts"])
        if b_last is not None:
            bpnl = (entry_basis - b_last) * n
            basis_total += bpnl
            trade_pnl += bpnl
        trades.append(trade_pnl)

    net = funding_total + basis_total - fees_total
    years = max(1e-9, (series[-1]["ts"] - series[0]["ts"]) / (365.25 * 24 * HOUR_MS)) if len(series) > 1 else 1e-9
    wins = sum(1 for t in trades if t > 0)
    return CarryResult(
        params=asdict(params),
        round_trips=len(trades),
        settlements_in_position=in_count,
        settlements_total=len(series),
        time_in_market_pct=(in_count / len(series) * 100.0) if series else 0.0,
        funding_collected_usd=funding_total,
        basis_pnl_usd=basis_total,
        fees_usd=fees_total,
        net_pnl_usd=net,
        capital_usd=capital,
        net_return_pct=net / capital * 100.0,
        annualized_return_pct=((1 + net / capital) ** (1 / years) - 1) * 100.0 if net / capital > -1 else -100.0,
        worst_trade_usd=min(trades) if trades else 0.0,
        best_trade_usd=max(trades) if trades else 0.0,
        win_rate_pct=(wins / len(trades) * 100.0) if trades else 0.0,
        years=years,
    )


def always_in_benchmark(series: list[dict[str, Any]], basis: dict[int, float], params: CarryParams) -> CarryResult:
    """Hold the carry the entire time (one entry, one exit) — the naive version."""
    naive = CarryParams(entry_rate=-1.0, exit_rate=-2.0, lookback=1, notional_usd=params.notional_usd,
                        spot_fee_pct=params.spot_fee_pct, perp_fee_pct=params.perp_fee_pct,
                        spread_cost_pct=params.spread_cost_pct, perp_margin_fraction=params.perp_margin_fraction)
    return simulate_carry(series, basis, naive)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def describe_series(series: list[dict[str, Any]]) -> dict[str, Any]:
    rates = [r["rate"] for r in series]
    real = [r["rate"] for r in series if r["source"] == "real"]
    pos = sum(1 for r in rates if r > 0)
    return {
        "from": fmt_ts(series[0]["ts"]) if series else None,
        "to": fmt_ts(series[-1]["ts"]) if series else None,
        "settlements": len(series),
        "real_settlements": len(real),
        "mean_8h_pct": statistics.fmean(rates) * 100 if rates else 0.0,
        "mean_annualized_pct": statistics.fmean(rates) * 3 * 365 * 100 if rates else 0.0,
        "p90_8h_pct": statistics.quantiles(rates, n=10)[-1] * 100 if len(rates) >= 10 else 0.0,
        "share_positive_pct": pos / len(rates) * 100 if rates else 0.0,
        "share_above_0_03_pct": sum(1 for r in rates if r >= 0.0003) / len(rates) * 100 if rates else 0.0,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    data = await load_dataset(pairs, args.days, Path(args.cache_dir))
    thresholds = [float(x) for x in args.entry_thresholds.split(",")]
    report: dict[str, Any] = {"days": args.days, "pairs": {}}

    for base in pairs:
        d = data[base]
        basis = hourly_basis(d["spot"], d["perp"])
        calib = calibrate(basis, d["funding"])
        if calib is None:
            report["pairs"][base] = {"error": "not enough overlapping funding/candle data to calibrate"}
            continue
        series = build_funding_series(basis, d["funding"], calib)
        entry: dict[str, Any] = {
            "calibration": asdict(calib),
            "series": describe_series(series),
            "results": [],
        }
        for thr in thresholds:
            params = CarryParams(entry_rate=thr, exit_rate=thr / 3, notional_usd=args.notional)
            entry["results"].append(asdict(simulate_carry(series, basis, params)))
        entry["always_in"] = asdict(always_in_benchmark(series, basis, CarryParams(entry_rate=0, exit_rate=0, notional_usd=args.notional)))
        report["pairs"][base] = entry

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
    print_report(report)
    return report


def print_report(report: dict[str, Any]) -> None:
    for base, entry in report["pairs"].items():
        print(f"\n=== {base}-USDT  ({report['days']}d window) ===")
        if "error" in entry:
            print("  ", entry["error"])
            continue
        c = entry["calibration"]
        s = entry["series"]
        print(f"  OKX-formula proxy vs real funding: n={c['n']}  R²={c['r2']:.2f}  rmse={c['rmse']*100:.4f}%/8h  "
              f"| real at 0.01% base: {c['share_real_at_base']*100:.0f}%  proxy at base: {c['share_pred_at_base']*100:.0f}%")
        print(f"  series {s['from']}..{s['to']}: {s['settlements']} settlements ({s['real_settlements']} real), "
              f"mean {s['mean_8h_pct']:.4f}%/8h ≈ {s['mean_annualized_pct']:.1f}%/yr, p90 {s['p90_8h_pct']:.4f}%, "
              f">0: {s['share_positive_pct']:.0f}%, ≥0.03%: {s['share_above_0_03_pct']:.0f}%")
        ai = entry["always_in"]
        print(f"  always-in benchmark: net {ai['net_pnl_usd']:+.0f}$ on {ai['capital_usd']:.0f}$ = {ai['annualized_return_pct']:+.1f}%/yr "
              f"(funding {ai['funding_collected_usd']:+.0f}, basis {ai['basis_pnl_usd']:+.0f}, fees {ai['fees_usd']:.0f})")
        print(f"  {'entry≥':>8} {'exit<':>8} {'trips':>5} {'in-mkt':>7} {'funding$':>9} {'basis$':>8} {'fees$':>7} {'net$':>8} {'ret/yr':>8} {'win%':>5} {'worst$':>8}")
        for r in entry["results"]:
            p = r["params"]
            print(f"  {p['entry_rate']*100:>7.3f}% {p['exit_rate']*100:>7.3f}% {r['round_trips']:>5} {r['time_in_market_pct']:>6.0f}% "
                  f"{r['funding_collected_usd']:>9.0f} {r['basis_pnl_usd']:>8.0f} {r['fees_usd']:>7.0f} {r['net_pnl_usd']:>8.0f} "
                  f"{r['annualized_return_pct']:>7.1f}% {r['win_rate_pct']:>4.0f}% {r['worst_trade_usd']:>8.0f}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", default="BTC,ETH,SOL,DOGE")
    p.add_argument("--days", type=int, default=730)
    p.add_argument("--notional", type=float, default=10_000.0, help="USD per leg")
    p.add_argument("--entry-thresholds", default="0.0001,0.0002,0.0003,0.0005", help="per-8h funding, comma separated")
    p.add_argument("--cache-dir", default="state/research_cache")
    p.add_argument("--json", default=None)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    asyncio.run(run(build_parser().parse_args(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
