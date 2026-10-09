from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.core.ict_reversal import Bars, Costs
from app.core.ict_v2 import DAY_MS, H4, V2Params, aggregate, daily_bias, find_pois, random_trades, simulate

M15 = 15 * 60 * 1000
D0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
P = V2Params(bias_sma_days=2, discount_lookback_h4=6, swing_lookback=4)
FREE = Costs(0.0, 0.0)

Bar = tuple[float, float, float, float]


def flat(n: int, px: float) -> list[Bar]:
    return [(px, px + 0.2, px - 0.2, px) for _ in range(n)]


def ramp(n: int, a: float, b: float) -> list[Bar]:
    out = []
    for k in range(n):
        o = a + (b - a) * k / n
        c = a + (b - a) * (k + 1) / n
        out.append((o, max(o, c) + 0.2, min(o, c) - 0.2, c))
    return out


def scenario(*, rising: bool = True) -> list[Bar]:
    """Days 0–2 trend, day 3: gap up (4H FVG), rally to 120, pull back into the FVG, sweep, MSS, FVG entry, target."""
    bars = ramp(288, 100.0, 103.0) if rising else ramp(288, 103.0, 100.0)
    bars += flat(16, 110.0)  # A  00–04
    bars += ramp(16, 111.0, 120.0)  # B  04–08 → 4H FVG [high(day2 20h), low(B)] ≈ [103.2, 110.8]
    bars += flat(32, 120.0)  # C, D
    e = [(120 - 1.5 * k, 120 - 1.5 * k + 0.1, 120 - 1.5 * (k + 1) - 0.1, 120 - 1.5 * (k + 1)) for k in range(6)]  # → 111
    e += [(111.0, 111.1, 110.4, 110.5)]  # arrival: low ≤ zone top 110.8 (and below the prior 4 lows → sweep)
    e += [(110.5, 110.5, 108.5, 109.0)]  # j: lowest low 108.5, bearish
    e += [(109.0, 110.5, 108.9, 110.4)]  # impulse, still under the reference high
    e += [(110.6, 116.5, 110.6, 116.2)]  # MSS + displacement; 15m FVG: high[j] 110.5 < low 110.6 → entry 110.6
    e += [(116.2, 116.3, 110.5, 111.0)]  # retrace fills 110.6
    e += [(111.0, 120.5, 110.9, 120.4)]  # runs to the range high 120 → target
    bars += e + flat(16 - len(e), 120.0)
    bars += flat(16, 120.0)
    return bars


def to_bars(rows: list[Bar]) -> Bars:
    return Bars("TEST-USDT", [D0 + k * M15 for k in range(len(rows))], [r[0] for r in rows], [r[1] for r in rows],
                [r[2] for r in rows], [r[3] for r in rows])


def test_aggregate_and_bias() -> None:
    b = to_bars(scenario())
    h4 = aggregate(b, H4)
    assert h4.ts[0] == D0 and h4.ts[1] - h4.ts[0] == H4
    assert h4.open[18] == 110.0 and h4.high[19] == pytest.approx(120.2)
    bias = daily_bias(aggregate(b, DAY_MS), 2)
    assert bias[D0 + 3 * DAY_MS] is True
    assert D0 not in bias  # no lookahead: needs two finished days first


def test_finds_htf_fvg() -> None:
    pois = find_pois(aggregate(to_bars(scenario()), H4), P)
    tops = [x.top for x in pois if x.kind == "fvg"]
    assert any(t == pytest.approx(110.8) for t in tops)


def test_full_ict_sequence_hits_range_high() -> None:
    trades = simulate(to_bars(scenario()), P, FREE)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry == pytest.approx(110.6)
    assert t.stop == pytest.approx(108.5 * 0.9995)
    assert t.target == pytest.approx(120.2)  # range high of the last 6 4H bars
    assert t.exit_reason == "target"
    assert t.r_multiple == pytest.approx((120.2 - 110.6) / (110.6 - 108.5 * 0.9995))


def test_no_trade_without_bias_or_displacement() -> None:
    assert simulate(to_bars(scenario(rising=False)), P, FREE) == []
    rows = scenario()
    i = 288 + 64 + 9  # the MSS bar
    rows[i] = (110.6, 111.5, 110.6, 111.4)  # small body, never closes above the reference high
    assert simulate(to_bars(rows), P, FREE) == []


def test_poi_only_mode_and_costs() -> None:
    b = to_bars(scenario())
    t = simulate(b, replace(P, max_r_pct=10.0), FREE, mode="poi")[0]
    assert t.entry == pytest.approx(110.8)  # buys the zone top on arrival
    assert t.stop < 104
    full = simulate(b, P, Costs(0.10, 0.05))[0]
    assert full.r_multiple < simulate(b, P, FREE)[0].r_multiple


def test_random_baseline() -> None:
    b = to_bars(scenario())
    sample = simulate(b, P, FREE)
    rnd = random_trades(b, 5, sample, P, FREE, random.Random(3))
    assert len(rnd) == 5
    assert all(r.entry > r.stop for r in rnd)
