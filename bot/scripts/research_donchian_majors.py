"""Runner for the pre-registered Donchian-on-majors spec (BTC, ETH, SOL, XRP).

    python -m scripts.research_donchian_majors

Uses the spot daily cache from research_xs_momentum (no network). Every run
is appended to the shared trial ledger so the cumulative trial count feeds
the Deflated Sharpe Ratio.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.donchian_majors import Bars, DonchianParams, SmaParams, backtest_portfolio
from app.core.xs_momentum import deflated_sharpe_ratio

CACHE = Path("state/research_cache/spot_daily")
LEDGER = Path("state/research_cache/xs_momentum_trials.jsonl")  # shared, cumulative
INSTS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"]
MAIN_START = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
OOS_START = int(datetime(2024, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)


def load(inst: str) -> Bars:
    rows = json.loads((CACHE / f"{inst}.json").read_text())
    return Bars(inst, [int(r[0]) for r in rows], [float(r[1]) for r in rows], [float(r[2]) for r in rows],
                [float(r[3]) for r in rows], [float(r[4]) for r in rows])


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def log_trial(tag: str, r: dict[str, Any]) -> None:
    with LEDGER.open("a") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "tag": tag, "params": r["params"],
                             "fee_pct": r["fee_pct"], "from": ts(r["from"]), "to": ts(r["to"]), "cagr_pct": r["cagr_pct"],
                             "sharpe": r["sharpe"], "max_drawdown_pct": r["max_drawdown_pct"]}) + "\n")


def row(label: str, r: dict[str, Any]) -> str:
    extra = f"  trips {r['round_trips']:>3}  win {r['win_rate_pct']:>3.0f}%  avgW {r['avg_win_pct']:>+6.1f}%  avgL {r['avg_loss_pct']:>+6.1f}%" if r["rule"] != "hold" else ""
    return f"  {label:24} CAGR {r['cagr_pct']:>6.1f}%  vol {r['ann_vol_pct']:>5.1f}%  Sharpe {r['sharpe']:>5.2f}  MDD {r['max_drawdown_pct']:>5.1f}%{extra}"


def main() -> None:
    import sys
    spec = 'v4' if '--spec' in sys.argv and sys.argv[sys.argv.index('--spec') + 1] == 'v4' else 'v3'
    risk = 5.0 if spec == 'v4' else None
    print(f'spec {spec}' + (f' — ATR position sizing, risk {risk}% of sleeve per trade' if risk else ''))
    bars = {i: load(i) for i in INSTS}
    base = DonchianParams(risk_pct=risk)
    variants = {
        "① buy & hold": ("hold", None),
        "② SMA100 filter": ("sma", SmaParams(100)),
        "DONCHIAN 55/20/ATR2": ("donchian", base),
        "③ Donchian + SMA100 exit": ("donchian", replace(base, sma_exit_days=100)),
    }
    results: dict[str, dict[str, dict[str, Any]]] = {}
    for period, start in (("MAIN 2021-01 →", MAIN_START), ("LAST 2 YEARS", OOS_START)):
        print(f"\n=== {period} (4 equal sleeves, 0.15%/side) ===")
        results[period] = {}
        for label, (rule, p) in variants.items():
            r = backtest_portfolio(bars, rule=rule, params=p, start_ts=start)
            if rule != "hold":
                log_trial(f"{spec}_{rule}_{'sma' if (p and getattr(p, 'sma_exit_days', None)) else 'base'}_{period[:4]}", r)
            results[period][label] = r
            print(row(label, r))
        d = results[period]["DONCHIAN 55/20/ATR2"]
        h = results[period]["① buy & hold"]
        print("  per coin (Donchian vs hold):")
        for inst in INSTS:
            a, b = d["per_inst"][inst], h["per_inst"][inst]
            print(f"    {inst:9} Donchian CAGR {a['cagr_pct']:>6.1f}% MDD {a['max_drawdown_pct']:>5.1f}% Sharpe {a['sharpe']:>5.2f} trips {a['round_trips']:>2} in-market {a['exposure_pct']:>3.0f}%"
                  f"  |  hold CAGR {b['cagr_pct']:>6.1f}% MDD {b['max_drawdown_pct']:>5.1f}% Sharpe {b['sharpe']:>5.2f}")
        if d["open_positions"]:
            print(f"  open now: {d['open_positions']}")

    print("\nreference — BTC & ETH only from 2018 (not used for the verdict):")
    ref_bars = {i: bars[i] for i in ("BTC-USDT", "ETH-USDT")}
    ref_start = int(datetime(2018, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
    for label, (rule, p) in (("① buy & hold", ("hold", None)), ("DONCHIAN 55/20/ATR2", ("donchian", base)), ("② SMA100 filter", ("sma", SmaParams(100)))):
        print(row(label, backtest_portfolio(ref_bars, rule=rule, params=p, start_ts=ref_start)))

    main_d = results["MAIN 2021-01 →"]["DONCHIAN 55/20/ATR2"]
    main_h = results["MAIN 2021-01 →"]["① buy & hold"]
    oos_d = results["LAST 2 YEARS"]["DONCHIAN 55/20/ATR2"]
    oos_h = results["LAST 2 YEARS"]["① buy & hold"]

    print("\ncost stress 0.30%/side (main):")
    stress = backtest_portfolio(bars, rule="donchian", params=base, start_ts=MAIN_START, fee_pct=0.30)
    log_trial(f"{spec}_donchian_cost_x2", stress)
    print(row("Donchian @0.30%", stress))

    print("\nneighbour grid (27, main):")
    grid = []
    for e in (40, 55, 70):
        for x in (15, 20, 25):
            for a in (1.5, 2.0, 2.5):
                r = backtest_portfolio(bars, rule="donchian", params=DonchianParams(e, x, 20, a, risk_pct=risk), start_ts=MAIN_START)
                log_trial(f"{spec}_grid_{e}_{x}_{a}", r)
                ok = r["max_drawdown_pct"] <= 0.6 * main_h["max_drawdown_pct"] and r["sharpe"] >= main_h["sharpe"]
                grid.append(ok)
                print(f"  entry {e} exit {x} atr {a}: CAGR {r['cagr_pct']:>6.1f}%  MDD {r['max_drawdown_pct']:>5.1f}%  Sharpe {r['sharpe']:>5.2f}  trips {r['round_trips']:>3}  {'PASS' if ok else 'fail'}")

    if spec == "v4":
        print("\nrisk-budget sensitivity (reported, not judged):")
        for rk in (3.0, 7.0):
            for per, st in (("main", MAIN_START), ("2y", OOS_START)):
                r = backtest_portfolio(bars, rule="donchian", params=replace(base, risk_pct=rk), start_ts=st)
                log_trial(f"v4_risk{rk:g}_{per}", r)
                print(row(f"risk {rk:g}% ({per})", r))
        avg_frac = []
        from app.core.donchian_majors import position_fraction
        from app.core.indicators import atr_wilder
        for inst, b in bars.items():
            a = atr_wilder(b.high, b.low, b.close, 20)
            fr = [position_fraction(b.close[k], a[k], base) for k in range(len(b.ts)) if a[k] and b.ts[k] >= MAIN_START]
            avg_frac.append((inst, statistics.fmean(fr)))
        print("  average entry fraction if signalled: " + ", ".join(f"{i.split('-')[0]} {f*100:.0f}%" for i, f in avg_frac))

    sharpes = [json.loads(l)["sharpe"] for l in LEDGER.read_text().splitlines() if l.strip()]
    n_trials = len(sharpes)
    var = statistics.pvariance([s / 365 ** 0.5 for s in sharpes]) if n_trials > 1 else 0.0
    dsr = deflated_sharpe_ratio(main_d["_daily_returns"], n_trials=n_trials, sharpe_variance_across_trials=var)

    c = []
    c.append((1, "MDD ≤ 60% of hold", main_d["max_drawdown_pct"] <= 0.6 * main_h["max_drawdown_pct"], f"{main_d['max_drawdown_pct']:.1f}% vs limit {0.6*main_h['max_drawdown_pct']:.1f}% (hold {main_h['max_drawdown_pct']:.1f}%)"))
    c.append((2, "Sharpe ≥ hold", main_d["sharpe"] >= main_h["sharpe"], f"{main_d['sharpe']:.2f} vs {main_h['sharpe']:.2f}"))
    c.append((3, "1·2 hold at 0.30%/side", stress["max_drawdown_pct"] <= 0.6 * main_h["max_drawdown_pct"] and stress["sharpe"] >= main_h["sharpe"], f"MDD {stress['max_drawdown_pct']:.1f}%, Sharpe {stress['sharpe']:.2f}"))
    c.append((4, "≥40 round trips", main_d["round_trips"] >= 40, f"{main_d['round_trips']}"))
    c.append((5, "≥80% of 27 neighbours pass 1·2", sum(grid) >= 22, f"{sum(grid)}/27"))
    c.append((6, "last 2y: MDD ≤ 60% of hold and CAGR > 0", oos_d["max_drawdown_pct"] <= 0.6 * oos_h["max_drawdown_pct"] and oos_d["cagr_pct"] > 0, f"MDD {oos_d['max_drawdown_pct']:.1f}% vs limit {0.6*oos_h['max_drawdown_pct']:.1f}%, CAGR {oos_d['cagr_pct']:.1f}%"))
    c.append((7, "DSR ≥ 0.90 (cumulative trials)", (dsr or 0) >= 0.90, f"DSR {dsr:.3f} over {n_trials} trials" if dsr is not None else "n/a"))
    print(f"\n=== pass criteria (spec {spec}) ===")
    for n, name, ok, detail in c:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail}")

    out = Path(f"state/research_cache/donchian_majors_{spec}_result.json")
    strip = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    out.write_text(json.dumps({p: {k: strip(v) for k, v in d.items()} for p, d in results.items()} | {"grid_pass": sum(grid), "dsr": dsr, "n_trials": n_trials}, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
