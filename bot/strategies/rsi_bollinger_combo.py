import numpy as np

from app.core.quant_research import (
    VolatilityRegime,
    classify_volatility_regime,
    compute_atr_pct,
    compute_bb_width_pct,
    volatility_profile_matches,
)
from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class RSIBollingerComboStrategy(BaseStrategy):
    """RSI + Bollinger Band combo strategy.

    Requires BOTH indicators to confirm before entering:
      - LONG  when RSI < oversold AND price < lower Bollinger Band
      - SHORT when RSI > overbought AND price > upper Bollinger Band
      - CLOSE when RSI returns to neutral zone (45–55)
      - HOLD  otherwise

    The dual confirmation filters out false signals that a single indicator
    would produce — e.g. RSI oversold but price is still mid-band = skip.
    """

    name = "rsi_bollinger_combo"

    def __init__(self) -> None:
        self._rsi_period: int = 14
        self._rsi_oversold: float = 35.0
        self._rsi_overbought: float = 65.0
        self._bb_period: int = 20
        self._bb_std: float = 2.0
        self._atr_period: int = 14
        self._volatility_filter_enabled: bool = False
        self._volatility_profile: str = "normal"

    @property
    def lookback_period(self) -> int:
        return 21

    def configure(self, params: dict) -> None:
        """Accept optional overrides for RSI, Bollinger Bands, and opt-in volatility filtering."""
        if "rsi_period" in params:
            period = int(params["rsi_period"])
            if period <= 0:
                raise ValueError("rsi_period must be a positive integer")
            self._rsi_period = period
        if "rsi_oversold" in params:
            self._rsi_oversold = float(params["rsi_oversold"])
        if "rsi_overbought" in params:
            self._rsi_overbought = float(params["rsi_overbought"])
        if "bb_period" in params:
            period = int(params["bb_period"])
            if period <= 0:
                raise ValueError("bb_period must be a positive integer")
            self._bb_period = period
        if "bb_std" in params:
            self._bb_std = float(params["bb_std"])
        if "atr_period" in params:
            period = int(params["atr_period"])
            if period <= 0:
                raise ValueError("atr_period must be a positive integer")
            self._atr_period = period
        if "volatility_filter_enabled" in params:
            self._volatility_filter_enabled = self._parse_bool(
                params["volatility_filter_enabled"],
                "volatility_filter_enabled",
            )
        if "volatility_profile" in params:
            profile = str(params["volatility_profile"]).strip().lower()
            if profile not in {"low", "normal", "high", "any"}:
                raise ValueError("volatility_profile must be one of: low, normal, high, any")
            self._volatility_profile = profile
        logger.info(
            "rsi_bollinger_combo_configured",
            rsi_period=self._rsi_period,
            rsi_oversold=self._rsi_oversold,
            rsi_overbought=self._rsi_overbought,
            bb_period=self._bb_period,
            bb_std=self._bb_std,
            atr_period=self._atr_period,
            volatility_filter_enabled=self._volatility_filter_enabled,
            volatility_profile=self._volatility_profile,
        )

    @staticmethod
    def _parse_bool(value: object, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"{name} must be a boolean")

    # ------------------------------------------------------------------ #
    # Indicator calculations                                               #
    # ------------------------------------------------------------------ #

    def _compute_rsi(self, closes: np.ndarray) -> float:
        """Compute RSI using Wilder's smoothed moving average."""
        if len(closes) < self._rsi_period + 1:
            return 50.0

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[: self._rsi_period]))
        avg_loss = float(np.mean(losses[: self._rsi_period]))

        for g, loss in zip(gains[self._rsi_period:], losses[self._rsi_period:]):
            avg_gain = (avg_gain * (self._rsi_period - 1) + g) / self._rsi_period
            avg_loss = (avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _compute_bollinger_bands(
        self, closes: np.ndarray
    ) -> tuple[float, float, float]:
        """Return (upper, middle, lower) Bollinger Bands using the last bb_period closes."""
        if len(closes) < self._bb_period:
            mid = float(closes[-1])
            return mid, mid, mid

        window = closes[-self._bb_period:]
        middle = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        upper = middle + self._bb_std * std
        lower = middle - self._bb_std * std
        return upper, middle, lower

    def _compute_volatility_regime(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        bb_upper: float,
        bb_middle: float,
        bb_lower: float,
    ) -> VolatilityRegime:
        bb_width_pct = compute_bb_width_pct(bb_upper, bb_middle, bb_lower)
        atr_pct = compute_atr_pct(highs, lows, closes, period=self._atr_period)
        return classify_volatility_regime(bb_width_pct, atr_pct)

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
        highs = np.array([c["high"] for c in all_candles], dtype=float)
        lows = np.array([c["low"] for c in all_candles], dtype=float)

        min_required = max(self._rsi_period + 1, self._bb_period)
        if len(closes) < min_required:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        rsi = self._compute_rsi(closes)
        bb_upper, bb_middle, bb_lower = self._compute_bollinger_bands(closes)
        price = float(candle["close"])
        volatility = self._compute_volatility_regime(highs, lows, closes, bb_upper, bb_middle, bb_lower)

        logger.debug(
            "rsi_bollinger_combo_indicators",
            pair=context.pair,
            rsi=round(rsi, 2),
            bb_upper=round(bb_upper, 4),
            bb_middle=round(bb_middle, 4),
            bb_lower=round(bb_lower, 4),
            price=round(price, 4),
            volatility_regime=volatility.regime,
            bb_width_pct=round(volatility.bb_width_pct, 4),
            atr_pct=round(volatility.atr_pct, 4),
        )

        position = context.current_position

        # Close signal: RSI returned to neutral zone
        if position is not None:
            if 45.0 <= rsi <= 55.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"rsi_neutral_zone rsi={rsi:.2f}",
                )

        # Entry signals: require dual confirmation from both indicators
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        long_condition = rsi < self._rsi_oversold and price < bb_lower
        short_condition = rsi > self._rsi_overbought and price > bb_upper

        if self._volatility_filter_enabled and (long_condition or short_condition):
            if not volatility_profile_matches(self._volatility_profile, volatility.regime):
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"blocked_by_volatility_profile regime={volatility.regime} "
                        f"target={self._volatility_profile} bb_width_pct={volatility.bb_width_pct:.4f} "
                        f"atr_pct={volatility.atr_pct:.4f}"
                    ),
                )

        if long_condition and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"rsi_oversold+below_lower_band rsi={rsi:.2f} price={price:.4f} bb_lower={bb_lower:.4f}",
            )
        if short_condition and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"rsi_overbought+above_upper_band rsi={rsi:.2f} price={price:.4f} bb_upper={bb_upper:.4f}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"rsi={rsi:.2f} price={price:.4f} bb=[{bb_lower:.4f},{bb_upper:.4f}]",
        )
