from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.core.xs_momentum import (
    CostModel,
    Series,
    XsMomentumParams,
    annualized_vol,
    backtest_xs_momentum,
    deflated_sharpe_ratio,
    is_monday,
    momentum_score,
    regime_on,
    select_universe,
    target_weights,
)

DAY_MS = 86_400_000
T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)  # a Monday


def make_series(inst: str, closes: list[float], *, volume: float = 1e6, start: int = T0) -> Series:
    ts = [start + i * DAY_MS for i in range(len(closes))]
    opens = [closes[0]] + closes[:-1]
    return Series(inst=inst, ts=ts, open=opens, close=closes, quote_volume=[volume] * len(closes))


def trend(n: int, start: float, daily: float, wobble: float = 0.0) -> list[float]:
    out = []
    p = start
    for i in range(n):
        p *= 1 + daily + wobble * math.sin(i / 5)
        out.append(p)
    return out


def test_is_monday_utc() -> None:
    assert is_monday(T0)
    assert not is_monday(T0 + DAY_MS)


def test_momentum_score_prefers_steady_uptrend() -> None:
    p = XsMomentumParams()
    # a perfectly smooth trend has zero realised vol → undefined score, so add a wobble
    up = trend(60, 100, 0.01, wobble=0.002)
    flat = [100.0] * 60
    down = trend(60, 100, -0.01, wobble=0.002)
    assert momentum_score(up, p) > 0
    assert momentum_score(down, p) < 0
    assert momentum_score(flat, p) is None  # zero vol → undefined
    assert momentum_score(up[:20], p) is None  # not enough history


def test_annualized_vol_scales_with_noise() -> None:
    calm = trend(60, 100, 0.001, wobble=0.001)
    wild = trend(60, 100, 0.001, wobble=0.05)
    assert annualized_vol(wild) > annualized_vol(calm) > 0


def test_regime_filter() -> None:
    assert regime_on(trend(120, 100, 0.005), 100) is True
    assert regime_on(trend(120, 100, -0.005), 100) is False
    assert regime_on(trend(50, 100, 0.005), 100) is False  # warmup


def test_select_universe_ranks_by_volume_and_history() -> None:
    p = XsMomentumParams(universe_size=2, min_history_days=10, volume_lookback_days=5)
    s = {
        "A": make_series("A", [1.0] * 30, volume=10),
        "B": make_series("B", [1.0] * 30, volume=30),
        "C": make_series("C", [1.0] * 30, volume=20),
        "NEW": make_series("NEW", [1.0] * 5, volume=1000, start=T0 + 25 * DAY_MS),
    }
    t = T0 + 29 * DAY_MS
    assert select_universe(s, t, p) == ["B", "C"]


def test_target_weights_inverse_vol_capped_and_vol_targeted() -> None:
    p = XsMomentumParams(max_weight=0.25, target_vol=10.0)  # huge target → no scaling
    w = target_weights({"A": 0.5, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0}, None, p)
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0
    assert max(w.values()) <= 0.25 + 1e-9  # A would be 1/3 uncapped
    # vol targeting scales the whole book down, never up
    rets = {k: [0.05 * ((-1) ** i) for i in range(30)] for k in ("A", "B")}  # ~95% annualised vol each
    w2 = target_weights({"A": 1.0, "B": 1.0}, rets, XsMomentumParams(max_weight=0.6, target_vol=0.25))
    assert sum(w2.values()) < 0.5
    w3 = target_weights({"A": 1.0, "B": 1.0}, {k: [0.0001] * 30 for k in ("A", "B")}, XsMomentumParams(max_weight=0.6, target_vol=0.25))
    assert pytest.approx(sum(w3.values()), abs=1e-9) == 1.0


def test_backtest_holds_cash_when_btc_below_sma_and_buys_leaders_otherwise() -> None:
    n = 400
    btc_up = trend(n, 100, 0.004, wobble=0.002)
    leader = trend(n, 10, 0.008, wobble=0.003)
    laggard = trend(n, 10, -0.002, wobble=0.003)
    s = {
        "BTC-USDT": make_series("BTC-USDT", btc_up, volume=5e8),
        "LEAD-USDT": make_series("LEAD-USDT", leader, volume=1e8),
        "LAG-USDT": make_series("LAG-USDT", laggard, volume=1e8),
    }
    p = XsMomentumParams(universe_size=3, min_history_days=120, top_n=2)
    res = backtest_xs_momentum(s, params=p, cost=CostModel(0.15))
    assert res["rebalances"] > 20
    assert res["regime_off_pct"] == 0.0
    held = {inst for wk in res["weekly"] for inst in wk["weights"]}
    assert "LEAD-USDT" in held and "LAG-USDT" not in held  # negative momentum never bought
    assert res["final_equity_usd"] > res["starting_equity_usd"]
    assert "benchmark_btc_hold" in res and "benchmark_equal_weight" in res
    assert len(res["equity_curve"]) == len(res["_daily_returns"]) + 1

    btc_down = trend(n, 100, -0.004, wobble=0.002)
    s["BTC-USDT"] = make_series("BTC-USDT", btc_down, volume=5e8)
    res_off = backtest_xs_momentum(s, params=p)
    assert res_off["regime_off_pct"] == 100.0
    assert res_off["trade_count"] == 0
    assert res_off["final_equity_usd"] == res_off["starting_equity_usd"]


def test_backtest_pays_fees_and_counts_entries() -> None:
    n = 300
    s = {
        "BTC-USDT": make_series("BTC-USDT", trend(n, 100, 0.003), volume=5e8),
        "A-USDT": make_series("A-USDT", trend(n, 1, 0.006, wobble=0.004), volume=1e8),
    }
    p = XsMomentumParams(universe_size=2, min_history_days=120, top_n=1)
    cheap = backtest_xs_momentum(s, params=p, cost=CostModel(0.0))
    dear = backtest_xs_momentum(s, params=p, cost=CostModel(0.30))
    assert dear["fees_usd"] > 0 == cheap["fees_usd"]
    assert dear["final_equity_usd"] < cheap["final_equity_usd"]
    assert dear["entries"] >= 1


def test_deflated_sharpe_ratio_penalises_many_trials() -> None:
    rets = [0.002 + 0.01 * math.sin(i) for i in range(400)]
    one = deflated_sharpe_ratio(rets, n_trials=1, sharpe_variance_across_trials=0.0)
    many = deflated_sharpe_ratio(rets, n_trials=50, sharpe_variance_across_trials=0.01)
    assert one is not None and many is not None
    assert one > many
    assert deflated_sharpe_ratio(rets[:10], n_trials=1, sharpe_variance_across_trials=0.0) is None


# ---------------------------------------------------------------- v2 ----------


def v2_params(**kw) -> XsMomentumParams:
    base = dict(universe_size=4, min_history_days=120, btc_default=True, relative_to_btc=True,
                target_vol=None, max_alts=2, entry_rank=5, exit_rank=10, max_weight=0.30, alt_total_cap=0.80)
    base.update(kw)
    return XsMomentumParams(**base)


def test_v2_holds_btc_when_no_alt_beats_it() -> None:
    n = 300
    s = {
        "BTC-USDT": make_series("BTC-USDT", trend(n, 100, 0.006, wobble=0.002), volume=5e8),
        "SLOW-USDT": make_series("SLOW-USDT", trend(n, 10, 0.002, wobble=0.003), volume=1e8),  # positive but weaker than BTC
    }
    res = backtest_xs_momentum(s, params=v2_params())
    for wk in res["weekly"]:
        if wk["regime_on"]:
            assert wk["weights"] == {"BTC-USDT": 1.0}
    assert res["entries"] == 1  # the single BTC entry; no alt ever qualifies


def test_v2_rotates_into_alt_that_beats_btc_and_keeps_btc_floor() -> None:
    n = 300
    s = {
        "BTC-USDT": make_series("BTC-USDT", trend(n, 100, 0.003, wobble=0.002), volume=5e8),
        "FAST-USDT": make_series("FAST-USDT", trend(n, 10, 0.010, wobble=0.004), volume=1e8),
        "SLOW-USDT": make_series("SLOW-USDT", trend(n, 10, 0.001, wobble=0.004), volume=1e8),
    }
    res = backtest_xs_momentum(s, params=v2_params())
    on = [wk for wk in res["weekly"] if wk["regime_on"]]
    assert on
    with_fast = [wk for wk in on if "FAST-USDT" in wk["weights"]]
    assert len(with_fast) > len(on) * 0.8
    for wk in with_fast:
        assert "SLOW-USDT" not in wk["weights"]  # weaker than BTC → never a candidate
        assert wk["weights"]["FAST-USDT"] <= 0.30 + 1e-9  # per-alt cap
        assert wk["weights"]["BTC-USDT"] >= 0.20 - 1e-9  # BTC floor via alt_total_cap
        assert pytest.approx(sum(wk["weights"].values()), abs=1e-9) == 1.0  # fully invested
    assert res["regime_off_pct"] == 0.0


def test_v2_rank_buffer_keeps_held_alt_until_it_falls_out() -> None:
    from app.core.xs_momentum import _v2_targets

    p = v2_params(max_alts=1, entry_rank=1, exit_rank=3)
    n = 60
    btc = make_series("BTC-USDT", trend(n, 100, 0.001, wobble=0.001))
    alts = {f"A{i}-USDT": make_series(f"A{i}-USDT", trend(n, 10, 0.004 + 0.001 * i, wobble=0.002)) for i in range(4)}
    series = {"BTC-USDT": btc, **alts}
    t = btc.ts[-1]
    vols = {k: 0.5 for k in alts}
    rets = {k: [0.0] * 30 for k in alts}
    scored = sorted(((0.004 + 0.001 * i, f"A{i}-USDT") for i in range(4)), reverse=True)  # A3 best … A0 worst
    # not holding anything → buy the #1 ranked only
    fresh = _v2_targets(scored, vols, rets, [], series, t, "BTC-USDT", p)
    assert set(fresh) == {"A3-USDT", "BTC-USDT"}
    # holding A2 (rank 2, within exit_rank 3) → kept, and no room for A3 because max_alts=1
    held = _v2_targets(scored, vols, rets, ["A2-USDT"], series, t, "BTC-USDT", p)
    assert set(held) == {"A2-USDT", "BTC-USDT"}
    # holding A0 (rank 4, outside exit_rank) → dropped, replaced by #1
    dropped = _v2_targets(scored, vols, rets, ["A0-USDT"], series, t, "BTC-USDT", p)
    assert set(dropped) == {"A3-USDT", "BTC-USDT"}
