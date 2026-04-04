import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class VolumeMomentumStrategy(BaseStrategy):
    """Volume-Weighted Momentum strategy.

    Uses three confirming signals before entering:
      - LONG  when price > VWAP AND volume_ratio > threshold AND momentum > +threshold%
      - SHORT when price < VWAP AND volume_ratio > threshold AND momentum < -threshold%
      - CLOSE when volume_ratio drops below 0.8 (momentum fading)
              OR price crosses back through VWAP
      - HOLD  otherwise

    High-volume breakouts have follow-through; low-volume moves fade.
    """

    name = "volume_momentum"

    def __init__(self) -> None:
        self._period: int = 14
        self._volume_threshold: float = 1.5
        self._momentum_threshold: float = 2.0  # percent

    @property
    def lookback_period(self) -> int:
        return 21

    def configure(self, params: dict) -> None:
        """Accept optional overrides: period, volume_threshold, momentum_threshold."""
        if "period" in params:
            period = int(params["period"])
            if period <= 0:
                raise ValueError("period must be a positive integer")
            self._period = period
        if "volume_threshold" in params:
            self._volume_threshold = float(params["volume_threshold"])
        if "momentum_threshold" in params:
            self._momentum_threshold = float(params["momentum_threshold"])
        logger.info(
            "volume_momentum_configured",
            period=self._period,
            volume_threshold=self._volume_threshold,
            momentum_threshold=self._momentum_threshold,
        )

    # ------------------------------------------------------------------ #
    # Indicator calculations                                               #
    # ------------------------------------------------------------------ #

    def _compute_vwap(self, candles: list[dict]) -> float:
        """Compute VWAP over the provided candle window."""
        closes = np.array([c["close"] for c in candles], dtype=float)
        volumes = np.array([c["volume"] for c in candles], dtype=float)
        total_volume = float(np.sum(volumes))
        if total_volume == 0.0:
            return float(closes[-1])
        return float(np.sum(closes * volumes) / total_volume)

    def _compute_volume_ratio(self, candles: list[dict]) -> float:
        """Compute current volume / average volume over the window."""
        volumes = np.array([c["volume"] for c in candles], dtype=float)
        avg_volume = float(np.mean(volumes[:-1])) if len(volumes) > 1 else float(volumes[0])
        current_volume = float(volumes[-1])
        if avg_volume == 0.0:
            return 1.0
        return current_volume / avg_volume

    def _compute_momentum(self, candles: list[dict]) -> float:
        """Compute price momentum = (close_now - close_N_periods_ago) / close_N_periods_ago * 100."""
        closes = np.array([c["close"] for c in candles], dtype=float)
        if len(closes) < self._period + 1:
            return 0.0
        close_now = float(closes[-1])
        close_prev = float(closes[-self._period - 1])
        if close_prev == 0.0:
            return 0.0
        return (close_now - close_prev) / close_prev * 100.0

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

        if len(all_candles) < self._period + 1:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        window = all_candles[-self._period:]
        vwap = self._compute_vwap(window)
        volume_ratio = self._compute_volume_ratio(all_candles[-self._period:])
        momentum = self._compute_momentum(all_candles)
        price = float(candle["close"])

        logger.debug(
            "volume_momentum_indicators",
            pair=context.pair,
            price=round(price, 4),
            vwap=round(vwap, 4),
            volume_ratio=round(volume_ratio, 3),
            momentum_pct=round(momentum, 3),
        )

        position = context.current_position

        # Close signals: momentum fading or price crossed back through VWAP
        if position is not None:
            direction = position.get("direction", "")
            momentum_fading = volume_ratio < 0.8
            vwap_cross_long = direction == "buy" and price < vwap
            vwap_cross_short = direction == "sell" and price > vwap
            if momentum_fading:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"volume_fading volume_ratio={volume_ratio:.3f}",
                )
            if vwap_cross_long or vwap_cross_short:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"vwap_cross price={price:.4f} vwap={vwap:.4f}",
                )

        # Entry signals: all three conditions must confirm
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        high_volume = volume_ratio > self._volume_threshold
        long_condition = price > vwap and high_volume and momentum > self._momentum_threshold
        short_condition = price < vwap and high_volume and momentum < -self._momentum_threshold

        if long_condition and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"price_above_vwap+high_volume+positive_momentum "
                    f"price={price:.4f} vwap={vwap:.4f} "
                    f"vol_ratio={volume_ratio:.3f} momentum={momentum:.2f}%"
                ),
            )
        if short_condition and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"price_below_vwap+high_volume+negative_momentum "
                    f"price={price:.4f} vwap={vwap:.4f} "
                    f"vol_ratio={volume_ratio:.3f} momentum={momentum:.2f}%"
                ),
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"price={price:.4f} vwap={vwap:.4f} "
                f"vol_ratio={volume_ratio:.3f} momentum={momentum:.2f}%"
            ),
        )
