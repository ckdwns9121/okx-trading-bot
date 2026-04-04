import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class SMACrossStrategy(BaseStrategy):
    """SMA crossover trend-following strategy.

    Signals:
      - LONG  when fast SMA crosses above slow SMA (golden cross)
      - SHORT when fast SMA crosses below slow SMA (death cross)
      - HOLD  otherwise
    """

    name = "example_sma_cross"

    def __init__(self) -> None:
        self._fast_period: int = 10
        self._slow_period: int = 30

    @property
    def lookback_period(self) -> int:
        # Need slow_period + 1 bars to detect a crossover
        return self._slow_period + 1

    def configure(self, params: dict) -> None:
        """Accept optional overrides: fast_period, slow_period."""
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
        if self._fast_period >= self._slow_period:
            raise ValueError("fast_period must be strictly less than slow_period")
        logger.info(
            "sma_cross_strategy_configured",
            fast_period=self._fast_period,
            slow_period=self._slow_period,
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

        # Need at least slow_period + 1 values to detect a one-bar crossover
        if len(closes) < self._slow_period + 1:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        # Compute SMAs for current and previous bar
        fast_now = float(np.mean(closes[-self._fast_period :]))
        fast_prev = float(np.mean(closes[-self._fast_period - 1 : -1]))
        slow_now = float(np.mean(closes[-self._slow_period :]))
        slow_prev = float(np.mean(closes[-self._slow_period - 1 : -1]))

        logger.debug(
            "sma_computed",
            pair=context.pair,
            fast_now=round(fast_now, 4),
            fast_prev=round(fast_prev, 4),
            slow_now=round(slow_now, 4),
            slow_prev=round(slow_prev, 4),
        )

        # Golden cross: fast crosses above slow
        crossed_above = fast_prev <= slow_prev and fast_now > slow_now
        # Death cross: fast crosses below slow
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        position = context.current_position
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if crossed_above and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"golden_cross fast={fast_now:.4f} slow={slow_now:.4f}"
                ),
            )

        if crossed_below and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"death_cross fast={fast_now:.4f} slow={slow_now:.4f}"
                ),
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"no_cross fast={fast_now:.4f} slow={slow_now:.4f}",
        )
