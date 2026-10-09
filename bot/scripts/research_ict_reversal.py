"""Runner for the pre-registered ICT reversal spec (15m, BTC/ETH/SOL/XRP, long only).

    python -m scripts.research_ict_reversal

Needs the 15m cache from scripts.fetch_intraday. Appends every portfolio run to
the shared cumulative trial ledger.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.ict_reversal import (
    Bars,
    Costs,
    IctParams,
    find_setups,
    perf,
    portfolio_curve,
    r_stats,
    random_bracket_trades,
)
from app.core.xs_momentum import deflated_sharpe_ratio

CACHE = Path("state/research_cache/spot_15m")
LEDGER = Path("state/research_cache/xs_momentum_trials.jsonl")
INSTS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"]
OOS_START = int(datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
SEEDS = 200
SLEEVE = 2500.0
RISK_PCT = 1.0


def load(inst: str) -> Bars:
    rows = json.loads((CACHE / f"{inst}.json").read_text())
    return Bars(inst, [int(r[0]) for r in rows], [float(r[1]) for r in rows], [float(r[2]) for r in rows],
                [float(r[3]) for r in rows], [float(r[4]) for r in rows])


def d(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def run(bars: dict[str, Bars], p: IctParams, c: Costs) -> dict[str, list]:
    return {inst: find_setups(b, p, c) for inst, b in bars.items()}


def pooled(tr: dict[str, list]) -> list:
    return [t for ts in tr.values() for t in ts]


def portfolio(tr: dict[str, list], bars: dict[str, Bars]) -> tuple[dict[str, float], list[float]]:
    start = min(b.ts[0] for b in bars.values())
    end = max(b.ts[-1] for b in bars.values())
    ts, curve = portfolio_curve(tr, sleeve_usd=SLEEVE, risk_pct=RISK_PCT, start_ts=start, end_ts=end)
    rets = [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve))]
    return perf(ts, curve), rets


def log_trial(tag: str, p: IctParams, c: Costs, stats: dict[str, float], pf: dict[str, float]) -> None:
    with LEDGER.open("a") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "tag": tag, "params": asdict(p), "fee_pct": c.fee_pct,
                             "mean_r": stats["mean_r"], "n": stats["n"], "cagr_pct": pf["cagr_pct"], "sharpe": pf["sharpe"],
                             "max_drawdown_pct": pf["max_drawdown_pct"]}) + "\n")


def line(label: str, s: dict[str, float]) -> str:
    return (f"  {label:22} n {s['n']:>4}  mean {s['mean_r']:>+6.3f}R  t {s['t']:>+5.2f}  win {s.get('win_rate_pct', 0):>3.0f}%  "
            f"target {s.get('target_pct', 0):>3.0f}% stop {s.get('stop_pct', 0):>3.0f}% eod {s.get('eod_pct', 0):>3.0f}%  "
            f"median R-dist {s.get('median_r_pct', 0):.2f}%")


def main() -> None:
    bars = {i: load(i) for i in INSTS}
    for i, b in bars.items():
        print(f"{i}: {len(b.ts):,} bars {d(b.ts[0])} → {d(b.ts[-1])}")
    base, cost = IctParams(), Costs()

    tr = run(bars, base, cost)
    s = r_stats(pooled(tr))
    pf, rets = portfolio(tr, bars)
    log_trial("ict_base", base, cost, s, pf)
    print("\n=== BASE (fee 0.10%/side, stop slip 0.05%) ===")
    print(line("pooled", s))
    for inst in INSTS:
        print(line(inst, r_stats(tr[inst])))
    print(f"  portfolio (4 × ${SLEEVE:,.0f}, {RISK_PCT}% risk/trade): CAGR {pf['cagr_pct']:.1f}%  Sharpe {pf['sharpe']:.2f}  MDD {pf['max_drawdown_pct']:.1f}%")

    # buy & hold over the same window
    hold = []
    for b in bars.values():
        hold.append(b.close[-1] / b.open[0] - 1)
    years = (max(b.ts[-1] for b in bars.values()) - min(b.ts[0] for b in bars.values())) / (365.25 * 86_400_000)
    print(f"  reference: 4-coin equal buy & hold total {statistics.fmean(hold)*100:+.0f}% over {years:.1f}y")

    # random-entry bracket baseline
    r_pcts = {inst: [t.r_pct for t in tr[inst]] for inst in INSTS}
    rand_means = []
    for seed in range(SEEDS):
        rng = random.Random(seed)
        rt = {inst: random_bracket_trades(bars[inst], len(tr[inst]), r_pcts[inst], base, cost, rng) for inst in INSTS}
        rand_means.append(r_stats(pooled(rt))["mean_r"])
    rand_means.sort()
    p95 = rand_means[int(0.95 * SEEDS) - 1]
    rank = sum(1 for m in rand_means if m < s["mean_r"]) / SEEDS * 100
    print(f"\nrandom killzone entries, same count & stop distances, {SEEDS} seeds: mean {statistics.fmean(rand_means):+.3f}R  "
          f"p5 {rand_means[int(0.05*SEEDS)]:+.3f}  p95 {p95:+.3f}  → ICT ranks above {rank:.0f}% of seeds")

    print("\ncost stress:")
    stress = {}
    for fee in (0.20, 0.30):
        c = replace(cost, fee_pct=fee)
        t2 = run(bars, base, c)
        s2 = r_stats(pooled(t2))
        pf2, _ = portfolio(t2, bars)
        log_trial(f"ict_fee{fee}", base, c, s2, pf2)
        stress[fee] = s2
        print(line(f"fee {fee:.2f}%", s2))

    print("\nlast year (2025-10 →):")
    oos = {inst: [t for t in ts if t.entry_ts >= OOS_START] for inst, ts in tr.items()}
    s_oos = r_stats(pooled(oos))
    print(line("pooled", s_oos))

    print("\nneighbour grid (27):")
    grid_ok = 0
    for sw in (6, 8, 12):
        for mw in (8, 12, 16):
            for tg in (1.5, 2.0, 2.5):
                p = replace(base, swing_lookback=sw, mss_window=mw, target_r=tg)
                tg_tr = run(bars, p, cost)
                sg = r_stats(pooled(tg_tr))
                pfg, _ = portfolio(tg_tr, bars)
                log_trial(f"ict_grid_{sw}_{mw}_{tg}", p, cost, sg, pfg)
                ok = sg["mean_r"] > 0 and sg["t"] >= 2
                grid_ok += ok
                print(f"  swing {sw:>2} mss {mw:>2} target {tg}R: n {sg['n']:>4}  mean {sg['mean_r']:>+6.3f}R  t {sg['t']:>+5.2f}  {'PASS' if ok else 'fail'}")

    sharpes = [json.loads(x)["sharpe"] for x in LEDGER.read_text().splitlines() if x.strip()]
    var = statistics.pvariance([x / 365 ** 0.5 for x in sharpes]) if len(sharpes) > 1 else 0.0
    dsr = deflated_sharpe_ratio(rets, n_trials=len(sharpes), sharpe_variance_across_trials=var)

    crit = [
        (1, "mean R > 0 and t ≥ 2 (fee 0.10%)", s["mean_r"] > 0 and s["t"] >= 2, f"{s['mean_r']:+.3f}R, t {s['t']:+.2f}"),
        (2, "beats 95th pct of random entries", s["mean_r"] >= p95, f"{s['mean_r']:+.3f}R vs p95 {p95:+.3f}R (rank {rank:.0f}%)"),
        (3, "mean R > 0 at fee 0.20%", stress[0.20]["mean_r"] > 0, f"{stress[0.20]['mean_r']:+.3f}R"),
        (4, "≥ 200 trades", s["n"] >= 200, f"{s['n']}"),
        (5, "≥ 22/27 neighbours pass 1", grid_ok >= 22, f"{grid_ok}/27"),
        (6, "last year mean R > 0", s_oos["mean_r"] > 0, f"{s_oos['mean_r']:+.3f}R over {s_oos['n']} trades"),
        (7, "DSR ≥ 0.90 (cumulative trials)", (dsr or 0) >= 0.90, f"{dsr:.3f} over {len(sharpes)} trials" if dsr is not None else "n/a"),
    ]
    print("\n=== pass criteria (ICT reversal spec) ===")
    for n, name, ok, detail in crit:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail}")

    out = Path("state/research_cache/ict_reversal_result.json")
    out.write_text(json.dumps({"base": s, "per_inst": {i: r_stats(tr[i]) for i in INSTS}, "portfolio": pf, "random_p95": p95,
                               "random_mean": statistics.fmean(rand_means), "rank_pct": rank, "stress": stress, "oos": s_oos,
                               "grid_ok": grid_ok, "dsr": dsr,
                               "trades": {i: [asdict(t) for t in tr[i]] for i in INSTS}}, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
