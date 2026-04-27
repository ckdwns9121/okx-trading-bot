from datetime import datetime, timedelta

import pytest

from app.core.strategy_base import Signal, TradingContext
from strategies.rsi_bollinger_regime import RSIBollingerRegimeStrategy


def candle(index: int, close: float = 100.0) -> dict:
    return {
        "timestamp": datetime(2026, 1, 1) + timedelta(minutes=index),
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }


def context() -> TradingContext:
    return TradingContext(
        current_position=None,
        account_balance=10_000.0,
        leverage=2,
        pair="BTC-USDT-SWAP",
    )


def force_long_setup(strategy: RSIBollingerRegimeStrategy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strategy, "_compute_rsi", lambda closes: 20.0)
    monkeypatch.setattr(strategy, "_compute_bollinger_bands", lambda closes: (110.0, 100.0, 95.0))
    monkeypatch.setattr(strategy, "_classify_regime", lambda closes, highs, lows: ("ranging", 10.0, 100.0, 100.0))


@pytest.mark.asyncio
async def test_default_regime_strategy_keeps_full_size_without_explicit_risk_prices(monkeypatch):
    strategy = RSIBollingerRegimeStrategy()
    strategy.configure({})
    force_long_setup(strategy, monkeypatch)

    history = [candle(i, 100.0) for i in range(strategy.lookback_period)]
    signal = await strategy.on_candle(candle(strategy.lookback_period, 90.0), history, context())

    assert signal.signal == Signal.LONG
    assert signal.size_pct == 100.0
    assert signal.tp_price is None
    assert signal.sl_price is None
    assert signal.trailing_stop_pct is None


@pytest.mark.asyncio
async def test_limited_risk_profile_adds_smaller_size_and_atr_exits(monkeypatch):
    strategy = RSIBollingerRegimeStrategy()
    strategy.configure({"risk_profile": "limited"})
    force_long_setup(strategy, monkeypatch)

    history = [candle(i, 100.0) for i in range(strategy.lookback_period)]
    signal = await strategy.on_candle(candle(strategy.lookback_period, 90.0), history, context())

    assert signal.signal == Signal.LONG
    assert signal.size_pct == 25.0
    assert signal.tp_price is not None and signal.tp_price > 90.0
    assert signal.sl_price is not None and signal.sl_price < 90.0
    assert signal.trailing_stop_pct == pytest.approx(0.025)


def test_limited_risk_profile_rejects_invalid_risk_values():
    strategy = RSIBollingerRegimeStrategy()

    with pytest.raises(ValueError, match="risk_profile"):
        strategy.configure({"risk_profile": "aggressive"})

    with pytest.raises(ValueError, match="size_pct"):
        strategy.configure({"size_pct": 0})

    with pytest.raises(ValueError, match="trailing_stop_pct"):
        strategy.configure({"trailing_stop_pct": 0})


@pytest.mark.asyncio
async def test_default_risk_profile_resets_limited_overlay(monkeypatch):
    strategy = RSIBollingerRegimeStrategy()
    strategy.configure({"risk_profile": "limited"})
    strategy.configure({"risk_profile": "default"})
    force_long_setup(strategy, monkeypatch)

    history = [candle(i, 100.0) for i in range(strategy.lookback_period)]
    signal = await strategy.on_candle(candle(strategy.lookback_period, 90.0), history, context())

    assert signal.signal == Signal.LONG
    assert signal.size_pct == 100.0
    assert signal.tp_price is None
    assert signal.sl_price is None
    assert signal.trailing_stop_pct is None
