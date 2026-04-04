import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """Z-Score mean-reversion strategy.

    Signals:
      - LONG  when Z-score < -entry_z  (price is significantly below mean)
      - SHORT when Z-score >  entry_z  (price is significantly above mean)
      - CLOSE when Z-score returns to within [-exit_z, exit_z] (reverted to mean)
      - HOLD  otherwise
    """

    name = "mean_reversion"

    def __init__(self) -> None:
        self._period: int = 30
        self._entry_z: float = 2.0
        self._exit_z: float = 0.5

    @property
    def lookback_period(self) -> int:
        # Need period bars to compute a valid mean and std dev
        return self._period + 1

    def configure(self, params: dict) -> None:
        """Accept optional overrides: period, entry_z, exit_z."""
        if "period" in params:
            period = int(params["period"])
            if period <= 1:
                raise ValueError("period must be greater than 1")
            self._period = period
        if "entry_z" in params:
            entry_z = float(params["entry_z"])
            if entry_z <= 0:
                raise ValueError("entry_z must be positive")
            self._entry_z = entry_z
        if "exit_z" in params:
            exit_z = float(params["exit_z"])
            if exit_z < 0:
                raise ValueError("exit_z must be non-negative")
            self._exit_z = exit_z
        if self._exit_z >= self._entry_z:
            raise ValueError("exit_z must be strictly less than entry_z")
        logger.info(
            "mean_reversion_strategy_configured",
            period=self._period,
            entry_z=self._entry_z,
            exit_z=self._exit_z,
        )

    # ------------------------------------------------------------------ #
    # Z-score calculation                                                  #
    # ------------------------------------------------------------------ #

    def _compute_zscore(self, closes: np.ndarray) -> float:
        """Compute Z-score of the most recent close relative to the rolling window."""
        window = closes[-self._period :]
        mean = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        if std == 0.0:
            return 0.0
        return (closes[-1] - mean) / std

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

        zscore = self._compute_zscore(closes)
        position = context.current_position

        logger.debug(
            "zscore_computed",
            pair=context.pair,
            zscore=round(zscore, 4),
            entry_z=self._entry_z,
            exit_z=self._exit_z,
        )

        # Close signals: Z-score has reverted to within the exit threshold
        if position is not None:
            if abs(zscore) <= self._exit_z:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"zscore_reverted zscore={zscore:.4f} exit_z={self._exit_z}",
                )

        # Entry signals: fire when flat OR when position is opposite direction (flip)
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        if zscore < -self._entry_z and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"zscore_below_entry zscore={zscore:.4f} entry_z=-{self._entry_z}",
            )
        if zscore > self._entry_z and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"zscore_above_entry zscore={zscore:.4f} entry_z={self._entry_z}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"zscore={zscore:.4f}",
        )
