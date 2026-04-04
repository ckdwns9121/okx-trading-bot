import numpy as np

from app.core.indicators import compute_atr, compute_rsi
from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class RSIStrategy(BaseStrategy):
    """RSI-based mean-reversion strategy.

    Signals:
      - LONG  when RSI < oversold (default 30)
      - SHORT when RSI > overbought (default 70)
      - CLOSE when RSI crosses back through 50 from either side
      - HOLD  otherwise
    """

    name = "example_rsi"

    def __init__(self) -> None:
        self._rsi_period: int = 14
        self._oversold: float = 50.0   # 테스트용: 원래 30.0
        self._overbought: float = 70.0
        self._atr_period: int = 14
        self._tp_atr_mult: float = 2.0    # take profit at 2x ATR
        self._sl_atr_mult: float = 1.5    # stop loss at 1.5x ATR
        self._trailing_stop_pct: float = 0.02  # 2% trailing stop

    @property
    def lookback_period(self) -> int:
        # Need rsi_period + 1 closes to compute the first RSI value
        return self._rsi_period + 1

    def configure(self, params: dict) -> None:
        """Accept optional overrides: rsi_period, oversold, overbought."""
        if "rsi_period" in params:
            period = int(params["rsi_period"])
            if period <= 0:
                raise ValueError("rsi_period must be a positive integer")
            self._rsi_period = period
        if "oversold" in params:
            self._oversold = float(params["oversold"])
        if "overbought" in params:
            self._overbought = float(params["overbought"])
        if "atr_period" in params:
            self._atr_period = int(params["atr_period"])
        if "tp_atr_mult" in params:
            self._tp_atr_mult = float(params["tp_atr_mult"])
        if "sl_atr_mult" in params:
            self._sl_atr_mult = float(params["sl_atr_mult"])
        if "trailing_stop_pct" in params:
            self._trailing_stop_pct = float(params["trailing_stop_pct"])
        logger.info(
            "rsi_strategy_configured",
            rsi_period=self._rsi_period,
            oversold=self._oversold,
            overbought=self._overbought,
        )

    # ------------------------------------------------------------------ #
    # Signal generation                                                    #
    # ------------------------------------------------------------------ #

    async def on_candle(
        self,
        candle: dict,
        history: list[dict],
        context: TradingContext,
    ) -> TradeSignal:
        all_candles = history + [candle]
        closes = np.array([c["close"] for c in all_candles], dtype=float)

        if len(closes) < self._rsi_period + 1:
            return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason="insufficient_history")

        rsi = compute_rsi(closes, self._rsi_period)
        position = context.current_position

        logger.debug("rsi_computed", pair=context.pair, rsi=round(rsi, 2))

        # Close signals: RSI crosses back through 50
        if position is not None:
            direction = position.get("direction", "")
            if direction == "buy" and rsi >= 50.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"rsi_cross_50_from_below rsi={rsi:.2f}",
                )
            if direction == "sell" and rsi <= 50.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"rsi_cross_50_from_above rsi={rsi:.2f}",
                )

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if rsi < self._oversold and not is_long:
            highs = np.array([c["high"] for c in all_candles], dtype=float)
            lows = np.array([c["low"] for c in all_candles], dtype=float)
            atr = compute_atr(highs, lows, closes, self._atr_period)
            tp_price = candle["close"] + atr * self._tp_atr_mult
            sl_price = candle["close"] - atr * self._sl_atr_mult
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"rsi_oversold rsi={rsi:.2f}",
                tp_price=tp_price,
                sl_price=sl_price,
                trailing_stop_pct=self._trailing_stop_pct,
            )
        if rsi > self._overbought and not is_short:
            highs = np.array([c["high"] for c in all_candles], dtype=float)
            lows = np.array([c["low"] for c in all_candles], dtype=float)
            atr = compute_atr(highs, lows, closes, self._atr_period)
            tp_price = candle["close"] - atr * self._tp_atr_mult
            sl_price = candle["close"] + atr * self._sl_atr_mult
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"rsi_overbought rsi={rsi:.2f}",
                tp_price=tp_price,
                sl_price=sl_price,
                trailing_stop_pct=self._trailing_stop_pct,
            )

        return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason=f"rsi={rsi:.2f}")
