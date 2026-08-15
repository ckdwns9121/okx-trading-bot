from __future__ import annotations

import pytest

from app.core.bband_rsi import BbandRsiParams, backtest_bband_rsi
from app.core.donchian import DonchianParams, backtest_donchian, decide
from app.core.indicators import atr_wilder, bollinger_bands, ema, rsi_wilder
from app.core.volatility_breakout import (
    VolatilityBreakoutParams,
    backtest_volatility_breakout,
    group_hourly_into_days,
)

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def make_daily(count: int, *, start: float = 100.0, step: float = 1.0) -> list[dict]:
    candles = []
    price = start
    for index in range(count):
        candles.append(
            {
                "timestamp": str(index * DAY_MS),
                "open": price,
                "high": price + abs(step) + 1.0,
                "low": price - abs(step) - 1.0,
                "close": price + step,
                "confirm": "1",
            }
        )
        price += step
    return candles


def make_hourly(hours: int, *, start: float = 100.0, step: float = 0.0) -> list[dict]:
    candles = []
    price = start
    for index in range(hours):
        candles.append(
            {
                "timestamp": str(index * HOUR_MS),
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + step,
                "confirm": "1",
            }
        )
        price += step
    return candles


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #


def test_ema_matches_hand_calc() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(values, 3)
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(2.0)
    assert result[3] == pytest.approx(3.0)
    assert result[4] == pytest.approx(4.0)


def test_rsi_extremes() -> None:
    rising = [float(i) for i in range(1, 30)]
    result = rsi_wilder(rising, 14)
    assert result[14] == pytest.approx(100.0)

    falling = [float(30 - i) for i in range(1, 30)]
    assert rsi_wilder(falling, 14)[14] == pytest.approx(0.0)


def test_atr_constant_range() -> None:
    highs = [11.0] * 20
    lows = [9.0] * 20
    closes = [10.0] * 20
    result = atr_wilder(highs, lows, closes, 14)
    assert result[14] == pytest.approx(2.0)
    assert result[19] == pytest.approx(2.0)


def test_bollinger_flat_series_collapses() -> None:
    closes = [50.0] * 25
    middle, upper, lower = bollinger_bands(closes, 20, 2.0)
    assert middle[19] == pytest.approx(50.0)
    assert upper[19] == pytest.approx(50.0)
    assert lower[19] == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# donchian
# --------------------------------------------------------------------------- #


def test_donchian_enters_on_breakout_and_exits_on_breakdown() -> None:
    params = DonchianParams(entry_period=5, exit_period=3, atr_period=5, atr_stop_mult=None)
    highs = [10.0] * 10
    lows = [9.0] * 10
    closes = [9.5] * 9 + [11.0]  # last close breaks the prior 5-day high
    decision = decide(
        highs=highs,
        lows=lows,
        closes=closes,
        in_position=False,
        entry_price=None,
        atr_at_entry=None,
        params=params,
    )
    assert decision.action == "enter"

    closes_down = [9.5] * 9 + [8.0]  # breaks the prior 3-day low
    decision = decide(
        highs=highs,
        lows=lows,
        closes=closes_down,
        in_position=True,
        entry_price=9.5,
        atr_at_entry=1.0,
        params=params,
    )
    assert decision.action == "exit"
    assert decision.reason == "breakdown_below_exit_channel"


def test_donchian_atr_stop_triggers() -> None:
    params = DonchianParams(entry_period=5, exit_period=3, atr_period=5, atr_stop_mult=2.0)
    highs = [10.0] * 10
    lows = [8.9] * 9 + [8.95]  # keep prior 3-day low below the close
    closes = [9.5] * 9 + [9.0]  # above prior low (8.9) but far below entry
    decision = decide(
        highs=highs,
        lows=lows,
        closes=closes,
        in_position=True,
        entry_price=12.0,
        atr_at_entry=1.0,
        params=params,
    )
    assert decision.action == "exit"
    assert decision.reason == "atr_stop"


def test_donchian_backtest_profits_in_trend() -> None:
    candles = []
    for index in range(80):
        close = 100.0 + index * 1.0
        candles.append(
            {
                "timestamp": str(index * DAY_MS),
                "open": close - 0.5,
                "high": close + 0.1,
                "low": close - 0.6,
                "close": close,
                "confirm": "1",
            }
        )
    result = backtest_donchian(
        {"BTC-USDT": candles},
        params=DonchianParams(entry_period=10, exit_period=5, atr_period=10),
    )
    assert result["trade_count"] >= 1
    assert result["total_return_pct"] > 0.0


# --------------------------------------------------------------------------- #
# volatility breakout
# --------------------------------------------------------------------------- #


def test_group_hourly_into_days() -> None:
    candles = make_hourly(48)
    days = group_hourly_into_days(candles)
    assert len(days) == 2
    assert days[0].first_index == 0
    assert days[1].first_index == 24


def test_volatility_breakout_triggers_on_spike() -> None:
    hours = 24 * 10
    candles = make_hourly(hours, start=100.0, step=0.01)
    # Day 8, hour 12: hourly close spikes far above open + 0.5*prev_range.
    spike = 24 * 8 + 12
    for offset in range(spike, hours):
        candles[offset]["close"] = float(candles[offset]["close"]) + 30.0
        candles[offset]["open"] = float(candles[offset]["open"]) + 30.0
        candles[offset]["high"] = float(candles[offset]["high"]) + 31.0
        candles[offset]["low"] = float(candles[offset]["low"]) + 29.0

    result = backtest_volatility_breakout(
        {"BTC-USDT": candles},
        params=VolatilityBreakoutParams(k=0.5, ma_period=3, use_ma_filter=False),
    )
    assert result["trade_count"] >= 2  # entry + next-day-open exit


def test_volatility_breakout_no_trade_in_flat_market() -> None:
    candles = make_hourly(24 * 10, start=100.0, step=0.0)
    result = backtest_volatility_breakout(
        {"BTC-USDT": candles},
        params=VolatilityBreakoutParams(k=0.5, ma_period=3, use_ma_filter=False),
    )
    assert result["trade_count"] == 0


# --------------------------------------------------------------------------- #
# bband rsi
# --------------------------------------------------------------------------- #


def test_bband_rsi_buys_dip_and_exits_on_recovery() -> None:
    closes = [100.0] * 30 + [100.0 - 2.0 * i for i in range(1, 11)]  # crash to 80
    closes += [80.0 + 3.0 * i for i in range(1, 21)]  # strong recovery
    candles = []
    for index, close in enumerate(closes):
        candles.append(
            {
                "timestamp": str(index * HOUR_MS),
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "confirm": "1",
            }
        )
    result = backtest_bband_rsi(
        {"BTC-USDT": candles},
        params=BbandRsiParams(),
    )
    assert result["trade_count"] >= 2
    assert result["total_return_pct"] > 0.0
