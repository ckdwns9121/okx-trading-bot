import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class BreakoutStrategy(BaseStrategy):
    """Donchian Channel breakout strategy.

    Signals:
      - LONG  when price breaks above the N-period high (upside breakout)
      - SHORT when price breaks below the N-period low (downside breakout)
      - CLOSE when price crosses back to the channel midpoint ((high + low) / 2)
      - HOLD  otherwise
    """

    name = "breakout_strategy"

    def __init__(self) -> None:
        self._channel_period: int = 20

    @property
    def lookback_period(self) -> int:
        # Need channel_period + 1 bars: channel is computed on history,
        # and the current candle is the breakout candidate
        return self._channel_period + 1

    def configure(self, params: dict) -> None:
        """Accept optional overrides: channel_period."""
        if "channel_period" in params:
            period = int(params["channel_period"])
            if period <= 1:
                raise ValueError("channel_period must be greater than 1")
            self._channel_period = period
        logger.info(
            "breakout_strategy_configured",
            channel_period=self._channel_period,
        )

    # ------------------------------------------------------------------ #
    # Channel calculation                                                  #
    # ------------------------------------------------------------------ #

    def _compute_channel(
        self, highs: np.ndarray, lows: np.ndarray
    ) -> tuple[float, float, float]:
        """Return (channel_high, channel_low, midpoint) over the lookback window."""
        window_highs = highs[-self._channel_period :]
        window_lows = lows[-self._channel_period :]
        ch_high = float(np.max(window_highs))
        ch_low = float(np.min(window_lows))
        midpoint = (ch_high + ch_low) / 2.0
        return ch_high, ch_low, midpoint

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

        if len(all_candles) < self._channel_period + 1:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        # Channel is computed on the previous N bars (excluding current candle)
        prior_candles = all_candles[-(self._channel_period + 1) : -1]
        prior_highs = np.array([c["high"] for c in prior_candles], dtype=float)
        prior_lows = np.array([c["low"] for c in prior_candles], dtype=float)

        ch_high, ch_low, midpoint = self._compute_channel(prior_highs, prior_lows)
        price = float(candle["close"])
        position = context.current_position

        logger.debug(
            "donchian_channel_computed",
            pair=context.pair,
            price=round(price, 6),
            ch_high=round(ch_high, 6),
            ch_low=round(ch_low, 6),
            midpoint=round(midpoint, 6),
        )

        # Close signals: price returns to the channel midpoint
        if position is not None:
            direction = position.get("direction", "")
            if direction == "long" and price <= midpoint:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"price_at_midpoint price={price:.6f} midpoint={midpoint:.6f}",
                )
            if direction == "short" and price >= midpoint:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"price_at_midpoint price={price:.6f} midpoint={midpoint:.6f}",
                )

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if price > ch_high and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"upside_breakout price={price:.6f} ch_high={ch_high:.6f}",
            )
        if price < ch_low and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"downside_breakout price={price:.6f} ch_low={ch_low:.6f}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"price={price:.6f} ch_high={ch_high:.6f} ch_low={ch_low:.6f}",
        )
