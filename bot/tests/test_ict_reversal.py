from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from app.core.ict_reversal import (
    Bars,
    Costs,
    IctParams,
    find_setups,
    in_killzone,
    random_bracket_trades,
    r_stats,
)

M15 = 15 * 60 * 1000
D0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)


def build(day1: list[tuple[float, float, float, float]], day2: list[tuple[float, float, float, float]]) -> Bars:
    """Two UTC days of 96 bars each; given bars overwrite the start of each day, the rest is flat."""
    ts, o, h, l, c = [], [], [], [], []
    for d, overrides in enumerate((day1, day2)):
        for k in range(96):
            t = D0 + d * 86_400_000 + k * M15
            bar = overrides[k] if k < len(overrides) else (100.0, 100.2, 99.8, 100.0)
            ts.append(t); o.append(bar[0]); h.append(bar[1]); l.append(bar[2]); c.append(bar[3])
    return Bars("TEST-USDT", ts, o, h, l, c)


def flat(n: int, px: float = 100.0) -> list[tuple[float, float, float, float]]:
    return [(px, px + 0.2, px - 0.2, px + (0.05 if k % 2 else -0.05)) for k in range(n)]


def textbook_day2(*, finish: str) -> list[tuple[float, float, float, float]]:
    """07:00 sweep of PDL (99.8), displacement up through the reference high, FVG, retrace fill, then finish."""
    bars = flat(28)  # 00:00–07:00, range 99.8–100.2
    bars += [(100.0, 100.1, 99.0, 99.3)]  # [28] 07:00 sweep: low 99.0 < PDL 99.8
    bars += [(99.3, 99.6, 99.2, 99.5)]  # [29] FVG bar k-2: high 99.6
    bars += [(99.5, 100.15, 99.5, 100.1)]  # [30] impulse, still closes below the reference high 100.2
    bars += [(100.1, 101.8, 100.4, 101.6)]  # [31] MSS + displacement; FVG k=31: 99.6 < 100.4 → CE 100.0
    bars += [(101.6, 101.7, 99.95, 100.3)]  # [32] retrace fills CE 100.0
    if finish == "target":
        bars += [(100.3, 102.2, 100.2, 102.1)]  # R = 100 − 98.95 ≈ 1.05 → 2R ≈ 102.1
    elif finish == "stop":
        bars += [(100.3, 100.4, 98.5, 98.7)]
    return bars


def test_killzones() -> None:
    assert in_killzone(D0 + 7 * 3_600_000, ((7, 10), (12, 15)))
    assert not in_killzone(D0 + 10 * 3_600_000, ((7, 10), (12, 15)))


def test_textbook_setup_hits_target() -> None:
    b = build(flat(96), textbook_day2(finish="target"))
    trades = find_setups(b, IctParams(), Costs(0.0, 0.0))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry == pytest.approx(100.0)
    assert t.stop == pytest.approx(99.0 * (1 - 0.0005))
    assert t.exit_reason == "target"
    assert t.r_multiple == pytest.approx(2.0)


def test_stop_and_costs() -> None:
    b = build(flat(96), textbook_day2(finish="stop"))
    t = find_setups(b, IctParams(), Costs(0.10, 0.05))[0]
    assert t.exit_reason == "stop"
    assert t.r_multiple < -1.0  # worse than −1R after fees and slippage


def test_no_trade_outside_killzone_or_without_displacement() -> None:
    late = flat(20) + textbook_day2(finish="target")[28:]  # sweep at 05:00
    assert find_setups(build(flat(96), late), IctParams(), Costs()) == []
    weak = textbook_day2(finish="target")
    weak[31] = (100.18, 100.3, 100.1, 100.25)  # tiny body closes above the reference high: no displacement
    assert find_setups(build(flat(96), weak), IctParams(), Costs()) == []


def test_random_baseline_matches_count_and_stats() -> None:
    b = build(flat(96), flat(96))
    rnd = random_bracket_trades(b, 1, [0.5], IctParams(), Costs(), random.Random(1))
    assert len(rnd) == 1 and rnd[0].exit_reason == "eod"
    s = r_stats(find_setups(build(flat(96), textbook_day2(finish="target")), IctParams(), Costs(0, 0)) * 3)
    assert s["n"] == 3 and s["mean_r"] == pytest.approx(2.0)
