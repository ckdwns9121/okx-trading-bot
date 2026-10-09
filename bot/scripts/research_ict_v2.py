"""Runner for the pre-registered ICT v2 spec (daily bias → 4H POI → 15m confirmation, long only).

    python -m scripts.research_ict_v2

Needs the 15m cache from scripts.fetch_intraday. Appends every portfolio run to the cumulative trial ledger.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from app.core.ict_reversal import Bars, Costs, perf, portfolio_curve, r_stats
from app.core.ict_v2 import H4, V2Params, aggregate, find_pois, random_trades, simulate
from app.core.xs_momentum import deflated_sharpe_ratio
from scripts.research_ict_reversal import INSTS, LEDGER, OOS_START, RISK_PCT, SEEDS, SLEEVE, d, load, pooled



def line(label: str, s: dict) -> str:
    return (f"  {label:22} n {s['n']:>4}  mean {s['mean_r']:>+6.3f}R  t {s['t']:>+5.2f}  win {s.get('win_rate_pct', 0):>3.0f}%  "
            f"target {s.get('target_pct', 0):>3.0f}% stop {s.get('stop_pct', 0):>3.0f}%  median R-dist {s.get('median_r_pct', 0):.2f}%")


def run(bars: dict[str, Bars], pois: dict, p: V2Params, c: Costs, mode: str = "full") -> dict[str, list]:
    return {i: simulate(b, p, c, mode, pois[i]) for i, b in bars.items()}


def portfolio(tr: dict[str, list], bars: dict[str, Bars]) -> tuple[dict, list[float]]:
    start = min(b.ts[0] for b in bars.values())
    end = max(b.ts[-1] for b in bars.values())
    ts, curve = portfolio_curve(tr, sleeve_usd=SLEEVE, risk_pct=RISK_PCT, start_ts=start, end_ts=end)
    return perf(ts, curve), [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve))]


def log_trial(tag: str, p: V2Params, c: Costs, s: dict, pf: dict) -> None:
    with LEDGER.open("a") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "tag": tag, "params": asdict(p), "fee_pct": c.fee_pct,
                             "mean_r": s["mean_r"], "n": s["n"], "cagr_pct": pf["cagr_pct"], "sharpe": pf["sharpe"],
                             "max_drawdown_pct": pf["max_drawdown_pct"]}) + "\n")


def main() -> None:
    bars = {i: load(i) for i in INSTS}
    for i, b in bars.items():
        print(f"{i}: {len(b.ts):,} bars {d(b.ts[0])} → {d(b.ts[-1])}")
    base, cost = V2Params(), Costs()
    pois = {i: find_pois(aggregate(b, H4), base) for i, b in bars.items()}
    for i in INSTS:
        k = Counter(x.kind for x in pois[i])
        print(f"  4H POIs {i}: FVG {k['fvg']}, OB {k['ob']}")

    tr = run(bars, pois, base, cost)
    s = r_stats(pooled(tr))
    pf, rets = portfolio(tr, bars)
    log_trial("ict_v2_base", base, cost, s, pf)
    exits = Counter(t.exit_reason for t in pooled(tr))
    print("\n=== L2 FULL ICT (fee 0.10%/side, stop slip 0.05%) ===")
    print(line("pooled", s), f" exits {dict(exits)}")
    for inst in INSTS:
        print(line(inst, r_stats(tr[inst])))
    print(f"  portfolio (4 × ${SLEEVE:,.0f}, {RISK_PCT}% risk/trade): CAGR {pf['cagr_pct']:.1f}%  Sharpe {pf['sharpe']:.2f}  MDD {pf['max_drawdown_pct']:.1f}%")

    l1 = run(bars, pois, base, cost, mode="poi")
    s1 = r_stats(pooled(l1))
    pf1, _ = portfolio(l1, bars)
    log_trial("ict_v2_poi_only", base, cost, s1, pf1)
    print("\n=== L1 POI ONLY (buy the 4H zone on arrival) ===")
    print(line("pooled", s1), f" exits {dict(Counter(t.exit_reason for t in pooled(l1)))}")
    print(f"  portfolio: CAGR {pf1['cagr_pct']:.1f}%  Sharpe {pf1['sharpe']:.2f}  MDD {pf1['max_drawdown_pct']:.1f}%")

    rand_means = []
    for seed in range(SEEDS):
        rng = random.Random(seed)
        rt = {i: random_trades(bars[i], len(tr[i]), tr[i] or pooled(tr), base, cost, rng) for i in INSTS}
        rand_means.append(r_stats(pooled(rt))["mean_r"])
    rand_means.sort()
    p95 = rand_means[int(0.95 * SEEDS) - 1]
    rank = sum(1 for m in rand_means if m < s["mean_r"]) / SEEDS * 100
    print(f"\n=== L0 RANDOM (bias days, same count & R shapes, {SEEDS} seeds) ===\n"
          f"  mean {statistics.fmean(rand_means):+.3f}R  p5 {rand_means[int(0.05 * SEEDS)]:+.3f}  p95 {p95:+.3f}  → ICT ranks above {rank:.0f}%")

    print("\ncost stress:")
    stress = {}
    for fee in (0.20, 0.30):
        c = replace(cost, fee_pct=fee)
        t2 = run(bars, pois, base, c)
        s2 = r_stats(pooled(t2))
        pf2, _ = portfolio(t2, bars)
        log_trial(f"ict_v2_fee{fee}", base, c, s2, pf2)
        stress[fee] = s2
        print(line(f"fee {fee:.2f}%", s2))

    oos = {i: [t for t in ts if t.entry_ts >= OOS_START] for i, ts in tr.items()}
    s_oos = r_stats(pooled(oos))
    print("\nlast year (2025-10 →):\n" + line("pooled", s_oos))

    print("\nneighbour grid (27):")
    grid_ok = 0
    for dm in (1.2, 1.5, 2.0):
        for sw in (6, 8, 12):
            for hold in (1, 3, 5):
                p = replace(base, ltf_disp_mult=dm, swing_lookback=sw, max_hold_bars=96 * hold)
                g = run(bars, pois, p, cost)
                sg = r_stats(pooled(g))
                pfg, _ = portfolio(g, bars)
                log_trial(f"ict_v2_grid_{dm}_{sw}_{hold}", p, cost, sg, pfg)
                ok = sg["mean_r"] > 0
                grid_ok += ok
                print(f"  disp {dm} swing {sw:>2} hold {hold}d: n {sg['n']:>4}  mean {sg['mean_r']:>+6.3f}R  t {sg['t']:>+5.2f}  {'PASS' if ok else 'fail'}")

    sharpes = [json.loads(x)["sharpe"] for x in LEDGER.read_text().splitlines() if x.strip()]
    var = statistics.pvariance([x / 365 ** 0.5 for x in sharpes]) if len(sharpes) > 1 else 0.0
    dsr = deflated_sharpe_ratio(rets, n_trials=len(sharpes), sharpe_variance_across_trials=var)

    crit = [
        (1, "mean R > 0 and t ≥ 2 (fee 0.10%)", s["mean_r"] > 0 and s["t"] >= 2, f"{s['mean_r']:+.3f}R, t {s['t']:+.2f}"),
        (2, "beats 95th pct of random entries", s["mean_r"] >= p95, f"{s['mean_r']:+.3f}R vs p95 {p95:+.3f}R (rank {rank:.0f}%)"),
        (3, "mean R > 0 at fee 0.20%", stress[0.20]["mean_r"] > 0, f"{stress[0.20]['mean_r']:+.3f}R"),
        (4, "≥ 200 trades", s["n"] >= 200, f"{s['n']}"),
        (5, "≥ 22/27 neighbours mean R > 0", grid_ok >= 22, f"{grid_ok}/27"),
        (6, "last year mean R > 0", s_oos["mean_r"] > 0, f"{s_oos['mean_r']:+.3f}R over {s_oos['n']} trades"),
        (7, "DSR ≥ 0.90 (cumulative trials)", (dsr or 0) >= 0.90, f"{dsr:.3f} over {len(sharpes)} trials" if dsr is not None else "n/a"),
    ]
    print("\n=== pass criteria (ICT v2 spec) ===")
    for n, name, ok, detail in crit:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail}")

    out = Path("state/research_cache/ict_v2_result.json")
    out.write_text(json.dumps({"base": s, "per_inst": {i: r_stats(tr[i]) for i in INSTS}, "portfolio": pf, "poi_only": s1,
                               "poi_only_portfolio": pf1, "random_p95": p95, "random_mean": statistics.fmean(rand_means),
                               "rank_pct": rank, "stress": stress, "oos": s_oos, "grid_ok": grid_ok, "dsr": dsr,
                               "trades": {i: [asdict(t) for t in tr[i]] for i in INSTS}}, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
