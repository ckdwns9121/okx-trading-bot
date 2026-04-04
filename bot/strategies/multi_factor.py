"""Multi-Factor scoring strategy.

Combines multiple independent factors into a composite score:
  1. Momentum — rate of change over N periods
  2. Trend Strength — ADX (Average Directional Index)
  3. Mean Reversion — RSI (overbought/oversold)
  4. Volume Anomaly — current volume vs moving average
  5. Volatility — ATR relative to price (normalized)
  6. Price Position — position within Bollinger Bands

Each factor produces a score from -1 (strongly bearish) to +1 (strongly bullish).
The weighted sum determines the final signal:
  - score > entry_threshold  → LONG
  - score < -entry_threshold → SHORT
  - |score| < exit_threshold (while in position) → CLOSE
"""

import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class MultiFactorStrategy(BaseStrategy):
    """Multi-factor composite scoring strategy."""

    name = "multi_factor"

    def __init__(self) -> None:
        # Factor periods
        self._momentum_period: int = 14
        self._adx_period: int = 14
        self._rsi_period: int = 14
        self._volume_period: int = 20
        self._atr_period: int = 14
        self._bb_period: int = 20
        self._bb_std: float = 2.0

        # Factor weights (must sum to 1.0)
        self._w_momentum: float = 0.25
        self._w_trend: float = 0.20
        self._w_rsi: float = 0.20
        self._w_volume: float = 0.15
        self._w_volatility: float = 0.10
        self._w_position: float = 0.10

        # Thresholds
        self._entry_threshold: float = 0.35
        self._exit_threshold: float = 0.10

    @property
    def lookback_period(self) -> int:
        return max(
            self._momentum_period,
            self._adx_period * 2,  # ADX needs 2× period for smoothing
            self._rsi_period,
            self._volume_period,
            self._atr_period,
            self._bb_period,
        ) + 5

    def configure(self, params: dict) -> None:
        if "momentum_period" in params:
            self._momentum_period = int(params["momentum_period"])
        if "adx_period" in params:
            self._adx_period = int(params["adx_period"])
        if "rsi_period" in params:
            self._rsi_period = int(params["rsi_period"])
        if "volume_period" in params:
            self._volume_period = int(params["volume_period"])
        if "bb_period" in params:
            self._bb_period = int(params["bb_period"])
        if "bb_std" in params:
            self._bb_std = float(params["bb_std"])

        # Weights
        if "w_momentum" in params:
            self._w_momentum = float(params["w_momentum"])
        if "w_trend" in params:
            self._w_trend = float(params["w_trend"])
        if "w_rsi" in params:
            self._w_rsi = float(params["w_rsi"])
        if "w_volume" in params:
            self._w_volume = float(params["w_volume"])
        if "w_volatility" in params:
            self._w_volatility = float(params["w_volatility"])
        if "w_position" in params:
            self._w_position = float(params["w_position"])

        # Thresholds
        if "entry_threshold" in params:
            self._entry_threshold = float(params["entry_threshold"])
        if "exit_threshold" in params:
            self._exit_threshold = float(params["exit_threshold"])

        # Normalize weights to sum to 1.0
        total = (
            self._w_momentum + self._w_trend + self._w_rsi
            + self._w_volume + self._w_volatility + self._w_position
        )
        if total > 0:
            self._w_momentum /= total
            self._w_trend /= total
            self._w_rsi /= total
            self._w_volume /= total
            self._w_volatility /= total
            self._w_position /= total

        logger.info(
            "multi_factor_configured",
            weights=dict(
                momentum=round(self._w_momentum, 3),
                trend=round(self._w_trend, 3),
                rsi=round(self._w_rsi, 3),
                volume=round(self._w_volume, 3),
                volatility=round(self._w_volatility, 3),
                position=round(self._w_position, 3),
            ),
            entry=self._entry_threshold,
            exit=self._exit_threshold,
        )

    # ------------------------------------------------------------------ #
    # Factor calculations — each returns a score in [-1, +1]             #
    # ------------------------------------------------------------------ #

    def _factor_momentum(self, closes: np.ndarray) -> float:
        """Rate of change: (close - close[N]) / close[N], clamped to [-1, 1]."""
        if len(closes) < self._momentum_period + 1:
            return 0.0
        roc = (closes[-1] - closes[-self._momentum_period - 1]) / closes[-self._momentum_period - 1]
        # Typical ROC range for crypto: ±20% over 14 bars → normalize by 0.1
        return float(np.clip(roc / 0.1, -1.0, 1.0))

    def _factor_trend_strength(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """ADX-based trend score. High ADX + up trend → +1, high ADX + down trend → -1."""
        period = self._adx_period
        if len(closes) < period * 2:
            return 0.0

        # True Range
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        # +DM / -DM
        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Smoothed averages (Wilder's smoothing)
        def wilder_smooth(arr: np.ndarray, n: int) -> np.ndarray:
            result = np.empty(len(arr))
            result[0] = np.mean(arr[:n]) if len(arr) >= n else arr[0]
            for i in range(1, len(arr)):
                result[i] = result[i - 1] - result[i - 1] / n + arr[i]
            return result

        atr = wilder_smooth(tr, period)
        plus_di_raw = wilder_smooth(plus_dm, period)
        minus_di_raw = wilder_smooth(minus_dm, period)

        # Avoid division by zero
        safe_atr = np.where(atr > 0, atr, 1.0)
        plus_di = 100.0 * plus_di_raw / safe_atr
        minus_di = 100.0 * minus_di_raw / safe_atr

        # DX and ADX
        di_sum = plus_di + minus_di
        safe_sum = np.where(di_sum > 0, di_sum, 1.0)
        dx = 100.0 * np.abs(plus_di - minus_di) / safe_sum
        adx = wilder_smooth(dx, period)

        adx_now = float(adx[-1])
        plus_now = float(plus_di[-1])
        minus_now = float(minus_di[-1])

        # ADX > 25 = trending. Normalize: ADX 0-50 → strength 0-1
        strength = min(adx_now / 50.0, 1.0)
        direction = 1.0 if plus_now > minus_now else -1.0

        return float(strength * direction)

    def _factor_rsi(self, closes: np.ndarray) -> float:
        """RSI mean-reversion score. RSI < 30 → +1 (oversold=buy), RSI > 70 → -1 (overbought=sell)."""
        period = self._rsi_period
        if len(closes) < period + 1:
            return 0.0

        deltas = np.diff(closes[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # RSI 50 = neutral (0), RSI 30 = +1 (oversold), RSI 70 = -1 (overbought)
        # Linear mapping: score = (50 - rsi) / 20, clamped
        return float(np.clip((50.0 - rsi) / 20.0, -1.0, 1.0))

    def _factor_volume(self, volumes: np.ndarray) -> float:
        """Volume anomaly: how much current volume exceeds average. High volume = conviction."""
        if len(volumes) < self._volume_period + 1:
            return 0.0
        avg_vol = float(np.mean(volumes[-(self._volume_period + 1):-1]))
        if avg_vol <= 0:
            return 0.0
        ratio = float(volumes[-1]) / avg_vol
        # ratio 1.0 = normal (0), 2.0+ = high conviction (+1)
        # This factor only indicates conviction, not direction — combine with other factors
        return float(np.clip((ratio - 1.0), -0.5, 1.0))

    def _factor_volatility(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """ATR-based volatility. Low vol = range-bound (mean revert), high vol = trending.

        Returns positive when vol is low (favoring mean reversion = contrarian),
        negative when vol is high (favoring caution).
        """
        period = self._atr_period
        if len(closes) < period + 1:
            return 0.0

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        atr = float(np.mean(tr[-period:]))
        price = float(closes[-1])
        if price <= 0:
            return 0.0

        # ATR as % of price. Crypto typical: 1-5%
        atr_pct = atr / price
        # Low vol (< 1.5%) = +0.5, high vol (> 3%) = -0.5
        return float(np.clip(0.5 - (atr_pct - 0.015) * 33.3, -1.0, 1.0))

    def _factor_price_position(self, closes: np.ndarray) -> float:
        """Position within Bollinger Bands. Below lower band = +1, above upper = -1."""
        if len(closes) < self._bb_period:
            return 0.0

        window = closes[-self._bb_period:]
        sma = float(np.mean(window))
        std = float(np.std(window))

        if std <= 0:
            return 0.0

        upper = sma + self._bb_std * std
        lower = sma - self._bb_std * std
        band_width = upper - lower

        if band_width <= 0:
            return 0.0

        price = float(closes[-1])
        # 0 = at lower band, 1 = at upper band
        position = (price - lower) / band_width
        # Invert: low position = bullish (+1), high position = bearish (-1)
        return float(np.clip(1.0 - 2.0 * position, -1.0, 1.0))

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

        if len(all_candles) < self.lookback_period:
            return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason="insufficient_history")

        closes = np.array([c["close"] for c in all_candles], dtype=float)
        highs = np.array([c["high"] for c in all_candles], dtype=float)
        lows = np.array([c["low"] for c in all_candles], dtype=float)
        volumes = np.array([c["volume"] for c in all_candles], dtype=float)

        # Compute all factors
        f_mom = self._factor_momentum(closes)
        f_trend = self._factor_trend_strength(highs, lows, closes)
        f_rsi = self._factor_rsi(closes)
        f_vol = self._factor_volume(volumes)
        f_volatility = self._factor_volatility(highs, lows, closes)
        f_pos = self._factor_price_position(closes)

        # Weighted composite score
        score = (
            self._w_momentum * f_mom
            + self._w_trend * f_trend
            + self._w_rsi * f_rsi
            + self._w_volume * f_vol
            + self._w_volatility * f_volatility
            + self._w_position * f_pos
        )

        logger.debug(
            "multi_factor_scores",
            pair=context.pair,
            momentum=round(f_mom, 3),
            trend=round(f_trend, 3),
            rsi=round(f_rsi, 3),
            volume=round(f_vol, 3),
            volatility=round(f_volatility, 3),
            position=round(f_pos, 3),
            composite=round(score, 4),
        )

        position = context.current_position
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        # Exit: score flipped or too weak while in position
        if is_long and score < self._exit_threshold:
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=f"score_below_exit score={score:.4f}",
            )
        if is_short and score > -self._exit_threshold:
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=f"score_above_exit score={score:.4f}",
            )

        # Entry
        if score > self._entry_threshold and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"bullish_composite score={score:.4f}",
            )
        if score < -self._entry_threshold and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"bearish_composite score={score:.4f}",
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=f"neutral score={score:.4f}",
        )
