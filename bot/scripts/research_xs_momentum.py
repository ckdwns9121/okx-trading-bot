"""Research runner for the pre-registered cross-sectional momentum spec.

    python -m scripts.research_xs_momentum fetch            # cache OKX spot daily candles (all USDT pairs)
    python -m scripts.research_xs_momentum run              # base params + cost stress + neighbour grid + criteria
    python -m scripts.research_xs_momentum run --quick      # base params only

Read-only: public endpoints, no orders. Every backtest run is appended to the
trial ledger (state/research_cache/xs_momentum_trials.jsonl) so the number of
things tried is known when the Deflated Sharpe Ratio is computed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.exchange.public_market_data import OKXPublicMarketData

CACHE_DIR = Path("state/research_cache/spot_daily")
LEDGER = Path("state/research_cache/xs_momentum_trials.jsonl")
STABLES = {
    "USDC", "DAI", "TUSD", "USDP", "FDUSD", "PYUSD", "USDE", "EURT", "EURC", "USD1", "USDG",
    "BUSD", "GUSD", "FRAX", "LUSD", "RLUSD", "USDD", "USDT", "USTC", "UST", "USDK", "USDS", "USDX",
}
LEVERAGED = re.compile(r"\d[LS]$")
EARLIEST_MS = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _is_eligible(base: str) -> bool:
    return base.upper() not in STABLES and not LEVERAGED.search(base.upper())


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #


async def _fetch_inst(market: OKXPublicMarketData, inst: str, sem: asyncio.Semaphore) -> list[list[Any]]:
    """All daily (UTC) candles for inst, oldest→newest, raw OKX rows incl. quote volume."""
    rows: dict[int, list[Any]] = {}
    after: str | None = None
    path = "/api/v5/market/candles"
    for _ in range(200):
        params = {"instId": inst, "bar": "1Dutc", "limit": "100"}
        if after:
            params["after"] = after
        async with sem:
            for attempt in range(8):
                try:
                    payload = await market._request(path, params=params)  # noqa: SLF001 — research script
                    break
                except Exception:  # 429 / transient — back off hard, OKX allows ~10 req/s per IP
                    if attempt == 7:
                        raise
                    await asyncio.sleep(3.0 * (attempt + 1))
            await asyncio.sleep(0.25)
        data = payload.get("data", [])
        if not data:
            if path.endswith("/candles"):
                path = "/api/v5/market/history-candles"
                continue
            break
        for r in data:
            if str(r[8] if len(r) > 8 else "1") == "1":
                rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in data)
        if oldest <= EARLIEST_MS or str(oldest) == after:
            break
        after = str(oldest)
        if path.endswith("/candles"):
            path = "/api/v5/market/history-candles"
    return [rows[k] for k in sorted(rows)]


async def cmd_fetch(args: argparse.Namespace) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    market = OKXPublicMarketData()
    try:
        insts = await market.get_instruments(inst_type="SPOT")
        pairs = sorted(
            x["instId"] for x in insts
            if x.get("quoteCcy") == "USDT" and x.get("state") == "live" and _is_eligible(str(x.get("baseCcy", "")))
        )
        states = {}
        for x in insts:
            states[x.get("state")] = states.get(x.get("state"), 0) + 1
        print(f"spot instruments: {len(insts)} (states {states}); eligible USDT pairs: {len(pairs)}", flush=True)
        sem = asyncio.Semaphore(2)
        done = 0
        started = time.time()

        async def one(inst: str) -> None:
            nonlocal done
            out = CACHE_DIR / f"{inst}.json"
            if out.exists() and not args.refresh:
                done += 1
                return
            rows = await _fetch_inst(market, inst, sem)
            out.write_text(json.dumps(rows))
            done += 1
            if done % 20 == 0 or done == len(pairs):
                first = datetime.fromtimestamp(int(rows[0][0]) / 1000, timezone.utc).date() if rows else None
                print(f"[{done}/{len(pairs)}] {inst}: {len(rows)} days from {first}  ({time.time()-started:.0f}s)", flush=True)

        await asyncio.gather(*(one(p) for p in pairs))
    finally:
        await market.close()
    summarize_cache()


def summarize_cache() -> None:
    files = sorted(CACHE_DIR.glob("*.json"))
    lens = []
    firsts = []
    for f in files:
        rows = json.loads(f.read_text())
        if rows:
            lens.append(len(rows))
            firsts.append(int(rows[0][0]))
    if not lens:
        print("cache empty")
        return
    by_year: dict[int, int] = {}
    for t in firsts:
        y = datetime.fromtimestamp(t / 1000, timezone.utc).year
        by_year[y] = by_year.get(y, 0) + 1
    print(f"cached {len(files)} pairs; median history {statistics.median(lens):.0f} days; "
          f"oldest {datetime.fromtimestamp(min(firsts)/1000, timezone.utc).date()}; first-candle year histogram {dict(sorted(by_year.items()))}")


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def load_series() -> dict[str, Any]:
    from app.core.xs_momentum import Series

    series: dict[str, Series] = {}
    for f in sorted(CACHE_DIR.glob("*.json")):
        rows = json.loads(f.read_text())
        if len(rows) < 40:
            continue
        inst = f.stem
        series[inst] = Series(
            inst=inst,
            ts=[int(r[0]) for r in rows],
            open=[float(r[1]) for r in rows],
            close=[float(r[4]) for r in rows],
            quote_volume=[float(r[7]) if len(r) > 7 and r[7] else float(r[6]) if len(r) > 6 else 0.0 for r in rows],
        )
    return series


def _ts(ms: int | None) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else "-"


def _log_trial(tag: str, result: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "params": result["params"],
        "cost": result["cost"],
        "from": _ts(result["from"]),
        "to": _ts(result["to"]),
        "cagr_pct": result["cagr_pct"],
        "sharpe": result["sharpe"],
        "max_drawdown_pct": result["max_drawdown_pct"],
        "entries": result["entries"],
        "btc_cagr_pct": result.get("benchmark_btc_hold", {}).get("cagr_pct"),
        "btc_mdd_pct": result.get("benchmark_btc_hold", {}).get("max_drawdown_pct"),
    }
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def _ledger_stats() -> tuple[int, float]:
    if not LEDGER.exists():
        return 0, 0.0
    sharpes = [json.loads(line)["sharpe"] for line in LEDGER.read_text().splitlines() if line.strip()]
    n = len(sharpes)
    # DSR wants per-period Sharpe variance; ledger stores annualised → de-annualise
    daily = [s / (365 ** 0.5) for s in sharpes]
    var = statistics.pvariance(daily) if n > 1 else 0.0
    return n, var


def _criteria(res: dict[str, Any], res_2x: dict[str, Any] | None, grid: list[dict[str, Any]], dsr: float | None) -> list[dict[str, Any]]:
    bh = res["benchmark_btc_hold"]
    ew = res["benchmark_equal_weight"]
    rows = []

    def add(num: int, name: str, ok: bool, detail: str) -> None:
        rows.append({"n": num, "name": name, "pass": ok, "detail": detail})

    add(1, "MDD ≤ 50% of BTC hold", res["max_drawdown_pct"] <= 0.5 * bh["max_drawdown_pct"],
        f"{res['max_drawdown_pct']:.1f}% vs BTC {bh['max_drawdown_pct']:.1f}% (limit {0.5*bh['max_drawdown_pct']:.1f}%)")
    add(2, "CAGR ≥ BTC hold − 5%p", res["cagr_pct"] >= bh["cagr_pct"] - 5.0,
        f"{res['cagr_pct']:.1f}% vs BTC {bh['cagr_pct']:.1f}%")
    if res_2x is not None:
        bh2 = res_2x["benchmark_btc_hold"]
        ok2 = res_2x["max_drawdown_pct"] <= 0.5 * bh2["max_drawdown_pct"] and res_2x["cagr_pct"] >= bh2["cagr_pct"] - 5.0
        add(3, "criteria 1·2 hold at 2× cost", ok2, f"CAGR {res_2x['cagr_pct']:.1f}%, MDD {res_2x['max_drawdown_pct']:.1f}% at 0.30%/side")
    else:
        add(3, "criteria 1·2 hold at 2× cost", False, "not run")
    add(4, "≥150 entries", res["entries"] >= 150, f"{res['entries']} entries, {res['trade_count']} fills")
    if grid:
        fails = [g for g in grid if not (g["max_drawdown_pct"] <= 0.5 * g["btc_mdd_pct"] and g["cagr_pct"] >= g["btc_cagr_pct"] - 5.0)]
        add(5, "all 27 neighbours pass 1·2", not fails, f"{len(grid)-len(fails)}/{len(grid)} pass")
    else:
        add(5, "all 27 neighbours pass 1·2", False, "grid not run")
    add(6, "Sharpe > equal-weight universe", res["sharpe"] > ew["sharpe"], f"{res['sharpe']:.2f} vs EW {ew['sharpe']:.2f}")
    add(7, "DSR ≥ 0.95", (dsr or 0.0) >= 0.95, f"DSR {dsr:.3f}" if dsr is not None else "n/a")
    return rows


def _print_result(title: str, r: dict[str, Any]) -> None:
    bh = r.get("benchmark_btc_hold", {})
    ew = r.get("benchmark_equal_weight", {})
    print(f"\n{title}  [{_ts(r['from'])} → {_ts(r['to'])}, {r['years']:.1f}y, {r['rebalances']} rebalances, regime off {r['regime_off_pct']:.0f}%]")
    print(f"  {'':16} {'CAGR':>8} {'vol':>7} {'Sharpe':>7} {'MDD':>7} {'MDD days':>9}")
    print(f"  {'strategy':16} {r['cagr_pct']:>7.1f}% {r['ann_vol_pct']:>6.1f}% {r['sharpe']:>7.2f} {r['max_drawdown_pct']:>6.1f}% {r['max_drawdown_days']:>9}")
    if bh:
        print(f"  {'BTC buy&hold':16} {bh['cagr_pct']:>7.1f}% {bh['ann_vol_pct']:>6.1f}% {bh['sharpe']:>7.2f} {bh['max_drawdown_pct']:>6.1f}% {bh['max_drawdown_days']:>9}")
        print(f"  {'equal-weight 30':16} {ew['cagr_pct']:>7.1f}% {ew['ann_vol_pct']:>6.1f}% {ew['sharpe']:>7.2f} {ew['max_drawdown_pct']:>6.1f}% {ew['max_drawdown_days']:>9}")
    print(f"  entries {r['entries']}, fills {r['trade_count']}, fees ${r['fees_usd']:.0f}, turnover {r['turnover_annual_pct']:.0f}%/yr, final ${r['final_equity_usd']:.0f}")


def cmd_run(args: argparse.Namespace) -> None:
    from app.core.xs_momentum import CostModel, XsMomentumParams, backtest_xs_momentum, deflated_sharpe_ratio

    series = load_series()
    print(f"loaded {len(series)} series", flush=True)
    base = XsMomentumParams()
    oos_start = int(datetime(2024, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)

    full = backtest_xs_momentum(series, params=base)
    _log_trial("base_full", full)
    _print_result("BASE — full period", full)
    oos = backtest_xs_momentum(series, params=base, start_ts=oos_start)
    _log_trial("base_oos", oos)
    _print_result("BASE — last 2 years", oos)

    if args.quick:
        return

    print("\ncost stress:", flush=True)
    stress = {}
    for mult in (2, 3):
        base_cost = 0.15 * mult
        c = CostModel(fee_pct_per_side=base_cost)
        r = backtest_xs_momentum(series, params=base, cost=c)
        _log_trial(f"cost_x{mult}", r)
        stress[mult] = r
        print(f"  {base_cost:.2f}%/side: CAGR {r['cagr_pct']:.1f}%  MDD {r['max_drawdown_pct']:.1f}%  Sharpe {r['sharpe']:.2f}  fees ${r['fees_usd']:.0f}")

    print("\nneighbour grid (27):", flush=True)
    grid: list[dict[str, Any]] = []
    for rs, rl in ((11, 22), (14, 28), (17, 34)):
        for top in (4, 5, 6):
            for sma in (80, 100, 120):
                p = replace(base, ret_short_days=rs, ret_long_days=rl, top_n=top, regime_sma_days=sma)
                r = backtest_xs_momentum(series, params=p)
                _log_trial(f"grid_{rs}_{rl}_{top}_{sma}", r)
                bh = r["benchmark_btc_hold"]
                row = {"ret": f"{rs}/{rl}", "top": top, "sma": sma, "cagr_pct": r["cagr_pct"], "sharpe": r["sharpe"],
                       "max_drawdown_pct": r["max_drawdown_pct"], "btc_cagr_pct": bh["cagr_pct"], "btc_mdd_pct": bh["max_drawdown_pct"], "entries": r["entries"]}
                grid.append(row)
                ok = row["max_drawdown_pct"] <= 0.5 * row["btc_mdd_pct"] and row["cagr_pct"] >= row["btc_cagr_pct"] - 5.0
                print(f"  ret {rs:>2}/{rl:<2} top {top} sma {sma:>3}: CAGR {r['cagr_pct']:>6.1f}%  MDD {r['max_drawdown_pct']:>5.1f}%  Sharpe {r['sharpe']:>5.2f}  {'PASS' if ok else 'fail'}")

    n_trials, var = _ledger_stats()
    dsr = deflated_sharpe_ratio(full["_daily_returns"], n_trials=n_trials, sharpe_variance_across_trials=var)
    print(f"\ntrial ledger: {n_trials} runs recorded; DSR of base (full) = {dsr if dsr is None else round(dsr, 3)}")

    for label, res, res2 in (("FULL PERIOD", full, stress[2]), ("LAST 2 YEARS", oos, None)):
        print(f"\n=== pass criteria — {label} ===")
        for row in _criteria(res, res2, grid if label == "FULL PERIOD" else [], dsr if label == "FULL PERIOD" else None):
            print(f"  [{'PASS' if row['pass'] else 'FAIL'}] {row['n']}. {row['name']}: {row['detail']}")

    out = Path(args.json) if args.json else Path("state/research_cache/xs_momentum_result.json")
    out.write_text(json.dumps({
        "base_full": {k: v for k, v in full.items() if not k.startswith("_")},
        "base_oos": {k: v for k, v in oos.items() if not k.startswith("_")},
        "stress": {str(k): {kk: vv for kk, vv in v.items() if not kk.startswith("_") and kk not in ("equity_curve", "weekly")} for k, v in stress.items()},
        "grid": grid,
        "n_trials": n_trials,
        "dsr": dsr,
    }, indent=1))
    print(f"\nwrote {out}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--refresh", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--quick", action="store_true")
    r.add_argument("--json", default=None)
    args = p.parse_args(argv)
    if args.cmd == "fetch":
        asyncio.run(cmd_fetch(args))
    else:
        cmd_run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
