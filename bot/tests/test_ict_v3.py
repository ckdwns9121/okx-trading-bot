from __future__ import annotations

import random

import pytest

from app.core.ict_reversal import Bars, Costs
from app.core.ict_v2 import H4
from app.core.ict_v3 import V3Params, divergences, rsi, simulate, supply_zones, walk_exit, random_trades

M15 = 15 * 60 * 1000
D0 = 1_767_571_200_000  # 2026-01-05 00:00 UTC


def bars_from_close(closes: list[float], spread: float = 0.1) -> Bars:
    o = [closes[0]] + closes[:-1]
    h = [max(a, c) + spread for a, c in zip(o, closes)]
    lo = [min(a, c) - spread for a, c in zip(o, closes)]
    return Bars("T", [D0 + k * M15 for k in range(len(closes))], o, h, lo, closes)


def test_rsi_bounds() -> None:
    up = rsi([float(k) for k in range(50)], 14)
    assert up[-1] == 100.0
    down = rsi([float(50 - k) for k in range(50)], 14)
    assert down[-1] == pytest.approx(0.0)


def test_bearish_fvg_supply_zone() -> None:
    h4 = Bars("T", [D0 + k * H4 for k in range(3)], [110, 105, 100], [110.5, 106, 100.5], [109, 101, 99], [109.5, 101.5, 99.5])
    z = supply_zones(h4, V3Params())
    assert len(z) == 1 and z[0].bottom == 100.5 and z[0].top == 109


def test_bullish_divergence_detected() -> None:
    closes = [100.0] * 20
    closes += [100 - 1.5 * k for k in range(1, 9)]  # fast drop to 88 (RSI very low)
    closes += [88 + 0.8 * k for k in range(1, 6)]  # bounce to 92
    closes += [92 - 0.6 * k for k in range(1, 8)]  # slow drift to 87.8: lower low, weaker momentum
    closes += [87.8 + 0.5 * k for k in range(1, 8)]
    b = bars_from_close(closes)
    bull, _ = divergences(b, V3Params())
    hits = [(i, q) for i, q in enumerate(bull) if q is not None]
    assert len(hits) == 1
    i, q = hits[0]
    assert b.low[q] == min(b.low) and i == q + 3  # confirmed 3 bars after the pivot


def test_exit_modes() -> None:
    closes = [100.0, 101, 103, 105, 104, 106, 103, 102, 101, 100]
    b = bars_from_close(closes)
    c = Costs(0.0, 0.0)
    k, px, why = walk_exit(b, 0, 95.0, 103.0, 50, c, "touch", [None] * 10)
    assert why == "target" and px == 103.0 and k == 2
    bear = [None] * 10
    bear[6] = 5  # bearish divergence at the high, confirmed on bar 6
    k, px, why = walk_exit(b, 0, 95.0, 103.0, 50, c, "div", bear)
    assert why == "div" and k == 7 and px == b.open[7]
    k, _, why = walk_exit(b, 2, 100.5, 107.0, 50, c, "div", [None] * 10)
    assert why == "stop" and k == 9


def test_simulate_on_random_walk_is_consistent() -> None:
    rng = random.Random(7)
    px, closes = 100.0, []
    for _ in range(96 * 60):
        px *= 1 + rng.gauss(0, 0.004)
        closes.append(px)
    b = bars_from_close(closes, spread=0.05)
    for em, xm in (("div", "div"), ("div", "touch"), ("zone", "touch")):
        trades = simulate(b, V3Params(), Costs(), em, xm)
        assert trades, (em, xm)
        prev_exit = -1
        for t in trades:
            assert t.stop < t.entry < t.target
            assert t.target - t.entry >= (t.entry - t.stop) * 0.999
            assert t.entry_ts > prev_exit  # one position at a time
            prev_exit = t.exit_ts
    sample = simulate(b, V3Params(), Costs())
    assert len(random_trades(b, 4, sample, V3Params(), Costs(), random.Random(1))) == 4
