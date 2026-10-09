"""Runner for the pre-registered ICT v3 spec (demand zone + bullish divergence → supply zone + bearish divergence).

    python -m scripts.research_ict_v3

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
from app.core.ict_v2 import H4, aggregate
from app.core.ict_v3 import V3Params, demand_zones, divergences, random_trades, simulate, supply_zones
from app.core.xs_momentum import deflated_sharpe_ratio
from scripts.research_ict_reversal import INSTS, LEDGER, OOS_START, RISK_PCT, SEEDS, SLEEVE, d, load, pooled


def line(label: str, s: dict) -> str:
    return (f"  {label:24} n {s['n']:>4}  mean {s['mean_r']:>+6.3f}R  t {s['t']:>+5.2f}  win {s.get('win_rate_pct', 0):>3.0f}%  "
            f"median R-dist {s.get('median_r_pct', 0):.2f}%")


def portfolio(tr: dict[str, list], bars: dict[str, Bars]) -> tuple[dict, list[float]]:
    start = min(b.ts[0] for b in bars.values())
    end = max(b.ts[-1] for b in bars.values())
    ts, curve = portfolio_curve(tr, sleeve_usd=SLEEVE, risk_pct=RISK_PCT, start_ts=start, end_ts=end)
    return perf(ts, curve), [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve))]


def log_trial(tag: str, p: V3Params, c: Costs, s: dict, pf: dict) -> None:
    with LEDGER.open("a") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "tag": tag, "params": asdict(p), "fee_pct": c.fee_pct,
                             "mean_r": s["mean_r"], "n": s["n"], "cagr_pct": pf["cagr_pct"], "sharpe": pf["sharpe"],
                             "max_drawdown_pct": pf["max_drawdown_pct"]}) + "\n")


def main() -> None:
    bars = {i: load(i) for i in INSTS}
    for i, b in bars.items():
        print(f"{i}: {len(b.ts):,} bars {d(b.ts[0])} → {d(b.ts[-1])}")
    base, cost = V3Params(), Costs()
    zones = {}
    for i, b in bars.items():
        h4 = aggregate(b, H4)
        zones[i] = (demand_zones(h4, base), supply_zones(h4, base))
        print(f"  {i}: demand zones {len(zones[i][0])}, supply zones {len(zones[i][1])}")
    div_cache: dict = {}

    def divs(i: str, p: V3Params):
        key = (i, p.rsi_len, p.pivot_w)
        if key not in div_cache:
            div_cache[key] = divergences(bars[i], p)
        return div_cache[key]

    def run(p: V3Params, c: Costs, em: str = "div", xm: str = "div") -> dict[str, list]:
        return {i: simulate(b, p, c, em, xm, zones[i], divs(i, p)) for i, b in bars.items()}

    layers = {}
    for tag, em, xm, label in (("L2", "div", "div", "L2 div buy → div sell"), ("L2t", "div", "touch", "L2t div buy → zone sell"),
                               ("L1t", "zone", "touch", "L1t zone buy → zone sell")):
        tr_l = run(base, cost, em, xm)
        s_l = r_stats(pooled(tr_l))
        pf_l, _ = portfolio(tr_l, bars)
        log_trial(f"ict_v3_{tag}", base, cost, s_l, pf_l)
        layers[tag] = (tr_l, s_l, pf_l)
        print(f"\n=== {label} ===")
        print(line("pooled", s_l), f" exits {dict(Counter(t.exit_reason for t in pooled(tr_l)))}")
        print(f"  portfolio (4 × ${SLEEVE:,.0f}, {RISK_PCT}% risk): CAGR {pf_l['cagr_pct']:.1f}%  Sharpe {pf_l['sharpe']:.2f}  MDD {pf_l['max_drawdown_pct']:.1f}%")
    tr, s, pf = layers["L2"]
    for inst in INSTS:
        print(line(f"L2 {inst}", r_stats(tr[inst])))
    _, rets = portfolio(tr, bars)

    rand_means = []
    for seed in range(SEEDS):
        rng = random.Random(seed)
        rt = {i: random_trades(bars[i], len(tr[i]), tr[i] or pooled(tr), base, cost, rng) for i in INSTS}
        rand_means.append(r_stats(pooled(rt))["mean_r"])
    rand_means.sort()
    p95 = rand_means[int(0.95 * SEEDS) - 1]
    rank = sum(1 for m in rand_means if m < s["mean_r"]) / SEEDS * 100
    print(f"\n=== L0 random ({SEEDS} seeds) ===\n  mean {statistics.fmean(rand_means):+.3f}R  p5 {rand_means[int(0.05 * SEEDS)]:+.3f}  "
          f"p95 {p95:+.3f}  → L2 ranks above {rank:.0f}%")

    print("\ncost stress (L2):")
    stress = {}
    for fee in (0.20, 0.30):
        c = replace(cost, fee_pct=fee)
        t2 = run(base, c)
        s2 = r_stats(pooled(t2))
        pf2, _ = portfolio(t2, bars)
        log_trial(f"ict_v3_fee{fee}", base, c, s2, pf2)
        stress[fee] = s2
        print(line(f"fee {fee:.2f}%", s2))

    oos = {i: [t for t in ts if t.entry_ts >= OOS_START] for i, ts in tr.items()}
    s_oos = r_stats(pooled(oos))
    print("\nlast year (2025-10 →):\n" + line("pooled", s_oos))

    print("\nneighbour grid (27):")
    grid_ok = 0
    for rl in (10, 14, 20):
        for pw in (2, 3, 5):
            for hold in (3, 5, 10):
                p = replace(base, rsi_len=rl, pivot_w=pw, max_hold_bars=96 * hold)
                g = run(p, cost)
                sg = r_stats(pooled(g))
                pfg, _ = portfolio(g, bars)
                log_trial(f"ict_v3_grid_{rl}_{pw}_{hold}", p, cost, sg, pfg)
                ok = sg["mean_r"] > 0
                grid_ok += ok
                print(f"  rsi {rl:>2} pivot {pw} hold {hold:>2}d: n {sg['n']:>4}  mean {sg['mean_r']:>+6.3f}R  t {sg['t']:>+5.2f}  {'PASS' if ok else 'fail'}")

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
    print("\n=== pass criteria (ICT v3 spec) ===")
    for n, name, ok, detail in crit:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail}")

    out = Path("state/research_cache/ict_v3_result.json")
    out.write_text(json.dumps({"layers": {k: {"stats": v[1], "portfolio": v[2]} for k, v in layers.items()},
                               "per_inst": {i: r_stats(tr[i]) for i in INSTS}, "random_p95": p95,
                               "random_mean": statistics.fmean(rand_means), "rank_pct": rank, "stress": stress, "oos": s_oos,
                               "grid_ok": grid_ok, "dsr": dsr, "trades": {i: [asdict(t) for t in tr[i]] for i in INSTS}}, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
