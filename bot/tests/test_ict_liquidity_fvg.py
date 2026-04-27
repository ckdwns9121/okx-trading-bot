from datetime import datetime, timedelta

import pytest

from app.core.strategy_base import Signal, TradingContext
from strategies.ict_liquidity_fvg import ICTLiquidityFVGStrategy


def candle(index: int, open_: float, high: float, low: float, close: float, volume: float = 1000.0) -> dict:
    return {
        "timestamp": datetime(2026, 1, 1) + timedelta(minutes=index),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


async def feed(strategy: ICTLiquidityFVGStrategy, candles: list[dict]):
    history: list[dict] = []
    signals = []
    context = TradingContext(current_position=None, account_balance=10_000.0, leverage=2, pair="BTC-USDT-SWAP")
    for c in candles:
        signals.append(await strategy.on_candle(c, history, context))
        history.append(c)
    return signals


def configured_strategy(**overrides) -> ICTLiquidityFVGStrategy:
    strategy = ICTLiquidityFVGStrategy()
    params = {
        "sweep_lookback": 5,
        "mss_lookback": 3,
        "mss_max_bars": 3,
        "fvg_max_bars": 3,
        "retest_max_bars": 3,
        "min_fvg_pct": 0.0,
        "sl_buffer_pct": 0.1,
        "reward_risk": 2.0,
        "size_pct": 10.0,
        "cooldown_bars": 0,
    }
    params.update(overrides)
    strategy.configure(params)
    return strategy


@pytest.mark.asyncio
async def test_bullish_sweep_mss_fvg_retest_emits_long_with_tp_sl():
    strategy = configured_strategy(direction_mode="long")
    candles = [
        candle(0, 98, 100, 96, 98),
        candle(1, 100, 101, 97, 100),
        candle(2, 101, 102, 98, 101),
        candle(3, 102, 103, 99, 102),
        candle(4, 100, 101, 95, 100),
        candle(5, 99, 100, 94, 97),  # sell-side liquidity sweep, closes back above 95
        candle(6, 97, 99, 96, 98),
        candle(7, 103, 105, 102, 104),  # MSS above 103 + bullish FVG [100, 102]
        candle(8, 104, 104, 101, 103),  # retest into FVG
    ]

    signals = await feed(strategy, candles)
    entry = signals[-1]

    assert entry.signal == Signal.LONG
    assert entry.size_pct == 10.0
    assert entry.leverage == 2
    assert entry.sl_price == pytest.approx(93.906)
    assert entry.tp_price == pytest.approx(121.188)
    assert "ict_bullish_retest_entry" in entry.reason
    assert "fvg=[100.000000,102.000000]" in entry.reason


@pytest.mark.asyncio
async def test_bearish_sweep_mss_fvg_retest_emits_short_with_tp_sl():
    strategy = configured_strategy(direction_mode="short")
    candles = [
        candle(0, 102, 104, 100, 102),
        candle(1, 103, 105, 101, 103),
        candle(2, 104, 106, 102, 104),
        candle(3, 105, 107, 103, 105),
        candle(4, 104, 105, 101, 104),
        candle(5, 107, 108, 104, 106),  # buy-side liquidity sweep, closes back below 107
        candle(6, 106, 107, 104, 105),
        candle(7, 101, 102, 99, 100),  # MSS below 101 + bearish FVG [102, 104]
        candle(8, 100, 103, 100, 101),  # retest into FVG
    ]

    signals = await feed(strategy, candles)
    entry = signals[-1]

    assert entry.signal == Signal.SHORT
    assert entry.sl_price == pytest.approx(108.108)
    assert entry.tp_price == pytest.approx(86.784)
    assert "ict_bearish_retest_entry" in entry.reason
    assert "fvg=[102.000000,104.000000]" in entry.reason


@pytest.mark.asyncio
async def test_insufficient_history_returns_hold():
    strategy = configured_strategy()
    signals = await feed(strategy, [candle(0, 100, 101, 99, 100)])

    assert signals[-1].signal == Signal.HOLD
    assert signals[-1].reason == "insufficient_history"


@pytest.mark.asyncio
async def test_direction_mode_blocks_disallowed_side():
    strategy = configured_strategy(direction_mode="short")
    candles = [
        candle(0, 98, 100, 96, 98),
        candle(1, 100, 101, 97, 100),
        candle(2, 101, 102, 98, 101),
        candle(3, 102, 103, 99, 102),
        candle(4, 100, 101, 95, 100),
        candle(5, 99, 100, 94, 97),
        candle(6, 97, 99, 96, 98),
        candle(7, 103, 105, 102, 104),
        candle(8, 104, 104, 101, 103),
    ]

    signals = await feed(strategy, candles)

    assert all(signal.signal != Signal.LONG for signal in signals)


@pytest.mark.asyncio
async def test_session_filter_blocks_retest_outside_utc_window():
    strategy = configured_strategy(
        direction_mode="long",
        session_filter_mode="utc",
        session_start_hour_utc=7,
        session_end_hour_utc=20,
    )
    candles = [
        candle(0, 98, 100, 96, 98),
        candle(1, 100, 101, 97, 100),
        candle(2, 101, 102, 98, 101),
        candle(3, 102, 103, 99, 102),
        candle(4, 100, 101, 95, 100),
        candle(5, 99, 100, 94, 97),
        candle(6, 97, 99, 96, 98),
        candle(7, 103, 105, 102, 104),
        candle(8, 104, 104, 101, 103),
    ]

    signals = await feed(strategy, candles)

    assert signals[-1].signal == Signal.HOLD
    assert "outside_session_utc" in signals[-1].reason


@pytest.mark.asyncio
async def test_directional_retest_confirmation_blocks_weak_retest_close():
    strategy = configured_strategy(
        direction_mode="long",
        retest_confirmation="directional_close",
    )
    candles = [
        candle(0, 98, 100, 96, 98),
        candle(1, 100, 101, 97, 100),
        candle(2, 101, 102, 98, 101),
        candle(3, 102, 103, 99, 102),
        candle(4, 100, 101, 95, 100),
        candle(5, 99, 100, 94, 97),
        candle(6, 97, 99, 96, 98),
        candle(7, 103, 105, 102, 104),
        candle(8, 104, 104, 101, 103),
    ]

    signals = await feed(strategy, candles)

    assert signals[-1].signal == Signal.HOLD
    assert "retest_not_bullish_close" in signals[-1].reason


def test_invalid_config_rejects_unsafe_values():
    strategy = ICTLiquidityFVGStrategy()

    with pytest.raises(ValueError, match="reward_risk"):
        strategy.configure({"reward_risk": 0})

    with pytest.raises(ValueError, match="size_pct"):
        strategy.configure({"size_pct": 0})

    with pytest.raises(ValueError, match="direction_mode"):
        strategy.configure({"direction_mode": "sideways"})

    with pytest.raises(ValueError, match="trend_filter_mode"):
        strategy.configure({"trend_filter_mode": "sma"})

    with pytest.raises(ValueError, match="max_atr_pct"):
        strategy.configure({"min_atr_pct": 2.0, "max_atr_pct": 1.0})
