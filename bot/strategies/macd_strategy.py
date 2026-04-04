import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class MACDStrategy(BaseStrategy):
    """MACD trend-following strategy.

    Signals:
      - LONG  when MACD line crosses above the Signal line (bullish crossover)
      - SHORT when MACD line crosses below the Signal line (bearish crossover)
      - CLOSE when the opposite crossover occurs while in a position
      - HOLD  otherwise
    """

    name = "macd_strategy"

    def __init__(self) -> None:
        self._fast_period: int = 12
        self._slow_period: int = 26
        self._signal_period: int = 9

    @property
    def lookback_period(self) -> int:
        # Need slow_period + signal_period bars to produce a valid MACD signal line
        return self._slow_period + self._signal_period

    def configure(self, params: dict) -> None:
        """Accept optional overrides: fast_period, slow_period, signal_period."""
        if "fast_period" in params:
            fast = int(params["fast_period"])
            if fast <= 0:
                raise ValueError("fast_period must be a positive integer")
            self._fast_period = fast
        if "slow_period" in params:
            slow = int(params["slow_period"])
            if slow <= 0:
                raise ValueError("slow_period must be a positive integer")
            self._slow_period = slow
        if "signal_period" in params:
            signal = int(params["signal_period"])
            if signal <= 0:
                raise ValueError("signal_period must be a positive integer")
            self._signal_period = signal
        if self._fast_period >= self._slow_period:
            raise ValueError("fast_period must be strictly less than slow_period")
        logger.info(
            "macd_strategy_configured",
            fast_period=self._fast_period,
            slow_period=self._slow_period,
            signal_period=self._signal_period,
        )

    # ------------------------------------------------------------------ #
    # EMA / MACD calculation                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> np.ndarray:
        """Compute EMA for the full array using the standard multiplier."""
        alpha = 2.0 / (period + 1)
        ema = np.empty(len(values), dtype=float)
        ema[0] = values[0]
        for i in range(1, len(values)):
            ema[i] = alpha * values[i] + (1.0 - alpha) * ema[i - 1]
        return ema

    def _compute_macd(
        self, closes: np.ndarray
    ) -> tuple[float, float, float, float]:
        """Return (macd_now, signal_now, macd_prev, signal_prev)."""
        ema_fast = self._ema(closes, self._fast_period)
        ema_slow = self._ema(closes, self._slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, self._signal_period)
        return (
            float(macd_line[-1]),
            float(signal_line[-1]),
            float(macd_line[-2]),
            float(signal_line[-2]),
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

        min_bars = self._slow_period + self._signal_period
        if len(closes) < min_bars:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        macd_now, signal_now, macd_prev, signal_prev = self._compute_macd(closes)
        position = context.current_position

        logger.debug(
            "macd_computed",
            pair=context.pair,
            macd_now=round(macd_now, 6),
            signal_now=round(signal_now, 6),
            macd_prev=round(macd_prev, 6),
            signal_prev=round(signal_prev, 6),
        )

        bullish_cross = macd_prev <= signal_prev and macd_now > signal_now
        bearish_cross = macd_prev >= signal_prev and macd_now < signal_now

        # Close signals: opposite crossover while in position
        if position is not None:
            direction = position.get("direction", "")
            if direction == "long" and bearish_cross:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"macd_bearish_cross macd={macd_now:.6f} signal={signal_now:.6f}",
                )
            if direction == "short" and bullish_cross:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"macd_bullish_cross macd={macd_now:.6f} signal={signal_now:.6f}",
                )

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if bullish_cross and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"macd_bullish_cross macd={macd_now:.6f} signal={signal_now:.6f}",
            )
        if bearish_cross and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"macd_bearish_cross macd={macd_now:.6f} signal={signal_now:.6f}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"macd={macd_now:.6f} signal={signal_now:.6f}",
        )
