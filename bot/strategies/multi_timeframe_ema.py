import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class MultiEMAStrategy(BaseStrategy):
    """Multi-EMA Trend + Mean Reversion strategy.

    Uses three EMAs to classify market regime, then trades pullbacks/rallies
    only when the trend is clear:
      - UPTREND   (fast > medium > slow): LONG on pullback to medium EMA
      - DOWNTREND (fast < medium < slow): SHORT on bounce to medium EMA
      - RANGING   (neither alignment):    HOLD — avoid choppy markets
      - CLOSE when trend regime changes

    This avoids the whipsaw losses common with single-EMA crossover systems.
    """

    name = "multi_ema"

    def __init__(self) -> None:
        self._fast: int = 8
        self._medium: int = 21
        self._slow: int = 55
        self._pullback_pct: float = 0.3  # % distance from medium EMA to trigger

    @property
    def lookback_period(self) -> int:
        return 55

    def configure(self, params: dict) -> None:
        """Accept optional overrides: fast, medium, slow, pullback_pct."""
        if "fast" in params:
            period = int(params["fast"])
            if period <= 0:
                raise ValueError("fast must be a positive integer")
            self._fast = period
        if "medium" in params:
            period = int(params["medium"])
            if period <= 0:
                raise ValueError("medium must be a positive integer")
            self._medium = period
        if "slow" in params:
            period = int(params["slow"])
            if period <= 0:
                raise ValueError("slow must be a positive integer")
            self._slow = period
        if "pullback_pct" in params:
            self._pullback_pct = float(params["pullback_pct"])
        logger.info(
            "multi_ema_configured",
            fast=self._fast,
            medium=self._medium,
            slow=self._slow,
            pullback_pct=self._pullback_pct,
        )

    # ------------------------------------------------------------------ #
    # Indicator calculations                                               #
    # ------------------------------------------------------------------ #

    def _compute_ema(self, closes: np.ndarray, period: int) -> float:
        """Compute EMA over closes using the standard recursive formula.

        k = 2 / (period + 1)
        ema[i] = price[i] * k + ema[i-1] * (1 - k)

        Seeded with a simple average of the first `period` values.
        """
        if len(closes) < period:
            return float(closes[-1])

        k = 2.0 / (period + 1)
        ema = float(np.mean(closes[:period]))
        for price in closes[period:]:
            ema = float(price) * k + ema * (1.0 - k)
        return ema

    def _compute_all_emas(
        self, closes: np.ndarray
    ) -> tuple[float, float, float]:
        """Return (fast_ema, medium_ema, slow_ema)."""
        return (
            self._compute_ema(closes, self._fast),
            self._compute_ema(closes, self._medium),
            self._compute_ema(closes, self._slow),
        )

    def _classify_trend(
        self, fast: float, medium: float, slow: float
    ) -> str:
        """Return 'uptrend', 'downtrend', or 'ranging'."""
        if fast > medium > slow:
            return "uptrend"
        if fast < medium < slow:
            return "downtrend"
        return "ranging"

    def _pullback_to_medium(self, price: float, medium_ema: float) -> bool:
        """True when price is within pullback_pct% of medium EMA or just crossed above it."""
        distance_pct = abs(price - medium_ema) / medium_ema * 100.0
        return distance_pct <= self._pullback_pct or price >= medium_ema

    def _bounce_to_medium(self, price: float, medium_ema: float) -> bool:
        """True when price is within pullback_pct% of medium EMA or just crossed below it."""
        distance_pct = abs(price - medium_ema) / medium_ema * 100.0
        return distance_pct <= self._pullback_pct or price <= medium_ema

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

        if len(closes) < self._slow:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        fast_ema, medium_ema, slow_ema = self._compute_all_emas(closes)
        trend = self._classify_trend(fast_ema, medium_ema, slow_ema)
        price = float(candle["close"])

        logger.debug(
            "multi_ema_indicators",
            pair=context.pair,
            price=round(price, 4),
            fast_ema=round(fast_ema, 4),
            medium_ema=round(medium_ema, 4),
            slow_ema=round(slow_ema, 4),
            trend=trend,
        )

        position = context.current_position

        # Close signal: trend regime changed while holding a position
        if position is not None:
            direction = position.get("direction", "")
            regime_broken = (
                (direction == "buy" and trend != "uptrend")
                or (direction == "sell" and trend != "downtrend")
            )
            if regime_broken:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"trend_changed trend={trend} direction={direction}",
                )

        # No trades in ranging market
        if trend == "ranging":
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=f"ranging fast={fast_ema:.4f} medium={medium_ema:.4f} slow={slow_ema:.4f}",
            )

        # Entry signals: trade pullbacks/bounces within a confirmed trend
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        long_condition = trend == "uptrend" and self._pullback_to_medium(price, medium_ema)
        short_condition = trend == "downtrend" and self._bounce_to_medium(price, medium_ema)

        if long_condition and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"uptrend_pullback_to_medium "
                    f"price={price:.4f} medium_ema={medium_ema:.4f} "
                    f"fast={fast_ema:.4f} slow={slow_ema:.4f}"
                ),
            )
        if short_condition and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"downtrend_bounce_to_medium "
                    f"price={price:.4f} medium_ema={medium_ema:.4f} "
                    f"fast={fast_ema:.4f} slow={slow_ema:.4f}"
                ),
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"trend={trend} price={price:.4f} "
                f"fast={fast_ema:.4f} medium={medium_ema:.4f} slow={slow_ema:.4f}"
            ),
        )
