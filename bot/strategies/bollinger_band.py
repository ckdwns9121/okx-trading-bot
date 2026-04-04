import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class BollingerBandStrategy(BaseStrategy):
    """Bollinger Band mean-reversion strategy.

    Signals:
      - LONG  when price closes below the lower band (oversold bounce)
      - SHORT when price closes above the upper band (overbought reversal)
      - CLOSE when price crosses back to the middle band (SMA)
      - HOLD  otherwise
    """

    name = "bollinger_band"

    def __init__(self) -> None:
        self._period: int = 20
        self._std_dev: float = 2.0

    @property
    def lookback_period(self) -> int:
        # Need period bars to compute the first valid band values
        return self._period + 1

    def configure(self, params: dict) -> None:
        """Accept optional overrides: period, std_dev."""
        if "period" in params:
            period = int(params["period"])
            if period <= 1:
                raise ValueError("period must be greater than 1")
            self._period = period
        if "std_dev" in params:
            std_dev = float(params["std_dev"])
            if std_dev <= 0:
                raise ValueError("std_dev must be positive")
            self._std_dev = std_dev
        logger.info(
            "bollinger_band_strategy_configured",
            period=self._period,
            std_dev=self._std_dev,
        )

    # ------------------------------------------------------------------ #
    # Band calculation                                                     #
    # ------------------------------------------------------------------ #

    def _compute_bands(self, closes: np.ndarray) -> tuple[float, float, float]:
        """Return (upper, middle, lower) Bollinger Bands using the last period bars."""
        window = closes[-self._period :]
        sma = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        upper = sma + self._std_dev * std
        lower = sma - self._std_dev * std
        return upper, sma, lower

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

        if len(closes) < self._period:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        upper, middle, lower = self._compute_bands(closes)
        price = closes[-1]
        position = context.current_position

        logger.debug(
            "bollinger_bands_computed",
            pair=context.pair,
            price=round(price, 6),
            upper=round(upper, 6),
            middle=round(middle, 6),
            lower=round(lower, 6),
        )

        # Close signals: price crosses back to the middle band
        if position is not None:
            direction = position.get("direction", "")
            if direction == "long" and price >= middle:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"price_reached_middle price={price:.6f} middle={middle:.6f}",
                )
            if direction == "short" and price <= middle:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"price_reached_middle price={price:.6f} middle={middle:.6f}",
                )

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if price < lower and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"price_below_lower price={price:.6f} lower={lower:.6f}",
            )
        if price > upper and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"price_above_upper price={price:.6f} upper={upper:.6f}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"price={price:.6f} upper={upper:.6f} lower={lower:.6f}",
        )
