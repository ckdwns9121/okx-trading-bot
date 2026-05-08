from datetime import datetime, timedelta

import pytest

from app.core.strategy_base import Signal, TradingContext
from strategies.ma_7d_5m import SevenDayMA5mStrategy


def candle(index: int, close: float = 100.0) -> dict:
    return {
        "timestamp": datetime(2026, 1, 1) + timedelta(minutes=5 * index),
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }


def context(position: dict | None = None) -> TradingContext:
    return TradingContext(
        current_position=position,
        account_balance=10_000.0,
        leverage=2,
        pair="BTC-USDT-SWAP",
    )


def configured_strategy(**overrides) -> SevenDayMA5mStrategy:
    strategy = SevenDayMA5mStrategy()
    params = {
        "ma_period": 5,
        "slope_lookback": 2,
        "atr_period": 3,
        "bb_period": 5,
        "min_bb_width_pct": 0.0,
        "min_bb_room_pct": 0.0,
    }
    params.update(overrides)
    strategy.configure(params)
    return strategy


def test_default_period_represents_seven_days_on_5m_candles():
    strategy = SevenDayMA5mStrategy()

    assert strategy.lookback_period == 2020  # 7 * 24 * 12 candles + 4-bar slope lookback


@pytest.mark.asyncio
async def test_insufficient_history_returns_hold():
    strategy = configured_strategy()
    history = [candle(i, 100.0) for i in range(5)]

    signal = await strategy.on_candle(candle(5, 101.0), history, context())

    assert signal.signal == Signal.HOLD
    assert signal.reason == "insufficient_history"


@pytest.mark.asyncio
async def test_cross_above_ma_arms_pending_long_then_next_candle_confirms_entry():
    strategy = configured_strategy()
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 99])]

    breakout = await strategy.on_candle(candle(6, 101.0), history, context())
    assert breakout.signal == Signal.HOLD
    assert "pending_long_after_7d_ma_breakout" in breakout.reason

    confirmation_history = history + [candle(6, 101.0)]
    signal = await strategy.on_candle(candle(7, 102.0), confirmation_history, context())
    assert signal.signal == Signal.LONG
    assert signal.leverage == 2
    assert signal.size_pct == 100.0
    assert signal.tp_price is not None and signal.tp_price > 102.0
    assert "long_confirmed_after_7d_ma_breakout" in signal.reason


@pytest.mark.asyncio
async def test_cross_below_ma_can_confirm_short_when_enabled():
    strategy = configured_strategy(direction_mode="both")
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 101])]

    breakout = await strategy.on_candle(candle(6, 99.0), history, context())
    assert breakout.signal == Signal.HOLD
    assert "pending_short_after_7d_ma_breakout" in breakout.reason

    confirmation_history = history + [candle(6, 99.0)]
    signal = await strategy.on_candle(candle(7, 98.0), confirmation_history, context())
    assert signal.signal == Signal.SHORT
    assert signal.leverage == 2
    assert signal.size_pct == 100.0
    assert signal.tp_price is not None and signal.tp_price < 98.0
    assert "short_confirmed_after_7d_ma_breakout" in signal.reason


@pytest.mark.asyncio
async def test_position_closes_when_price_loses_ma_side():
    strategy = configured_strategy()
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 101])]
    position = {"direction": "buy", "entry_price": 101.0, "quantity": 1.0}

    signal = await strategy.on_candle(candle(6, 99.0), history, context(position))

    assert signal.signal == Signal.CLOSE
    assert "lost_7d_ma_support" in signal.reason


@pytest.mark.asyncio
async def test_long_position_closes_when_price_reaches_upper_bollinger_band(monkeypatch):
    strategy = configured_strategy()
    monkeypatch.setattr(strategy, "_compute_bollinger_bands", lambda closes: (101.0, 100.0, 99.0))
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 101])]
    position = {"direction": "buy", "entry_price": 100.0, "quantity": 1.0}

    signal = await strategy.on_candle(candle(6, 102.0), history, context(position))

    assert signal.signal == Signal.CLOSE
    assert "bb_upper_take_profit" in signal.reason


@pytest.mark.asyncio
async def test_direction_mode_can_block_disallowed_entry_side():
    strategy = configured_strategy(direction_mode="short")
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 99])]

    signal = await strategy.on_candle(candle(6, 101.0), history, context())

    assert signal.signal == Signal.HOLD
    assert signal.reason == "long_blocked_by_direction_mode"


@pytest.mark.asyncio
async def test_limited_risk_profile_adds_size_and_atr_exits():
    strategy = configured_strategy(risk_profile="limited")
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 99])]

    breakout = await strategy.on_candle(candle(6, 101.0), history, context())
    assert breakout.signal == Signal.HOLD

    confirmation_history = history + [candle(6, 101.0)]
    signal = await strategy.on_candle(candle(7, 102.0), confirmation_history, context())
    assert signal.signal == Signal.LONG
    assert signal.size_pct == 25.0
    assert signal.tp_price is not None and signal.tp_price > 102.0
    assert signal.sl_price is not None and signal.sl_price < 102.0
    assert signal.trailing_stop_pct == pytest.approx(0.025)


@pytest.mark.asyncio
async def test_pending_long_is_blocked_when_bollinger_upper_room_is_too_small():
    strategy = configured_strategy(min_bb_room_pct=10.0)
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 99])]

    breakout = await strategy.on_candle(candle(6, 101.0), history, context())
    assert breakout.signal == Signal.HOLD

    confirmation_history = history + [candle(6, 101.0)]
    signal = await strategy.on_candle(candle(7, 102.0), confirmation_history, context())

    assert signal.signal == Signal.HOLD
    assert "pending_long_bb_room_blocked" in signal.reason


@pytest.mark.asyncio
async def test_pending_long_is_cancelled_if_next_candle_fails_to_hold_ma():
    strategy = configured_strategy()
    history = [candle(i, close) for i, close in enumerate([100, 100, 100, 100, 100, 99])]

    breakout = await strategy.on_candle(candle(6, 101.0), history, context())
    assert breakout.signal == Signal.HOLD

    confirmation_history = history + [candle(6, 101.0)]
    signal = await strategy.on_candle(candle(7, 99.0), confirmation_history, context())

    assert signal.signal == Signal.HOLD
    assert "pending_long_invalidated" in signal.reason


def test_configure_rejects_invalid_values():
    strategy = SevenDayMA5mStrategy()

    with pytest.raises(ValueError, match="ma_period"):
        strategy.configure({"ma_period": 1})

    with pytest.raises(ValueError, match="direction_mode"):
        strategy.configure({"direction_mode": "spot-only"})

    with pytest.raises(ValueError, match="bb_period"):
        strategy.configure({"bb_period": 1})

    with pytest.raises(ValueError, match="bb_std"):
        strategy.configure({"bb_std": 0})

    with pytest.raises(ValueError, match="size_pct"):
        strategy.configure({"size_pct": 0})

    with pytest.raises(ValueError, match="trailing_stop_pct"):
        strategy.configure({"trailing_stop_pct": 0})
