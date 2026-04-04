"""Market regime detection from recent price data using ADX, ATR, EMA, and Bollinger Bands."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class RegimeResult:
    """Result of market regime detection."""

    regime: str  # "trending_up", "trending_down", "ranging", "volatile"
    confidence: float  # 0.0-1.0
    adx: float  # Average Directional Index (trend strength)
    volatility: float  # ATR / price as percentage
    trend_direction: float  # positive = up, negative = down
    details: dict = field(default_factory=dict)  # additional metrics


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Compute Exponential Moving Average."""
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def _true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """Compute True Range array (length = len(closes) - 1, starting from index 1)."""
    prev_close = closes[:-1]
    h = highs[1:]
    lo = lows[1:]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_close), np.abs(lo - prev_close)))
    return tr


def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Compute the latest ADX value using a 14-period window."""
    n = len(closes)
    if n < period * 2 + 1:
        return 0.0

    # Directional Movement
    up_move = highs[1:] - highs[:-1]
    down_move = lows[:-1] - lows[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = _true_range(highs, lows, closes)

    # Smoothed averages using Wilder's smoothing (EMA with alpha=1/period)
    atr_smooth = _wilder_smooth(tr, period)
    plus_dm_smooth = _wilder_smooth(plus_dm, period)
    minus_dm_smooth = _wilder_smooth(minus_dm, period)

    # Avoid division by zero
    atr_safe = np.where(atr_smooth == 0, 1e-10, atr_smooth)
    plus_di = 100.0 * plus_dm_smooth / atr_safe
    minus_di = 100.0 * minus_dm_smooth / atr_safe

    di_sum = plus_di + minus_di
    di_sum_safe = np.where(di_sum == 0, 1e-10, di_sum)
    dx = 100.0 * np.abs(plus_di - minus_di) / di_sum_safe

    # ADX is smoothed DX
    adx_values = _wilder_smooth(dx, period)
    return float(adx_values[-1])


def _wilder_smooth(data: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing method (equivalent to EMA with alpha=1/period)."""
    result = np.empty_like(data, dtype=float)
    if len(data) < period:
        result[:] = np.mean(data)
        return result
    result[:period] = np.mean(data[:period])
    alpha = 1.0 / period
    for i in range(period, len(data)):
        result[i] = result[i - 1] * (1 - alpha) + data[i] * alpha
    return result


def _atr_pct(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Compute ATR as a percentage of the latest close."""
    if len(closes) < period + 1:
        return 0.0
    tr = _true_range(highs, lows, closes)
    atr_values = _wilder_smooth(tr, period)
    latest_atr = float(atr_values[-1])
    latest_close = float(closes[-1])
    if latest_close == 0:
        return 0.0
    return (latest_atr / latest_close) * 100.0


def _bollinger_band_width(closes: np.ndarray, period: int = 20, num_std: float = 2.0) -> float:
    """Compute Bollinger Band width as a percentage of the middle band."""
    if len(closes) < period:
        return 0.0
    recent = closes[-period:]
    mid = float(np.mean(recent))
    if mid == 0:
        return 0.0
    std = float(np.std(recent, ddof=0))
    width = (2 * num_std * std) / mid * 100.0
    return width


class MarketRegimeDetector:
    """Detects current market regime from recent price data."""

    def detect(
        self,
        closes: list[float],
        volumes: list[float],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> RegimeResult:
        """Analyse recent price data and classify the market regime.

        Parameters
        ----------
        closes : list[float]
            Close prices (oldest first).
        volumes : list[float]
            Volume data (oldest first).
        highs : list[float] | None
            High prices. If None, uses closes.
        lows : list[float] | None
            Low prices. If None, uses closes.

        Returns
        -------
        RegimeResult
        """
        closes_arr = np.array(closes, dtype=float)
        highs_arr = np.array(highs if highs is not None else closes, dtype=float)
        lows_arr = np.array(lows if lows is not None else closes, dtype=float)

        n = len(closes_arr)
        if n < 30:
            return RegimeResult(
                regime="ranging",
                confidence=0.0,
                adx=0.0,
                volatility=0.0,
                trend_direction=0.0,
                details={"error": "insufficient_data", "candle_count": n},
            )

        # 1. ADX — trend strength
        adx_val = _adx(highs_arr, lows_arr, closes_arr, period=14)

        # 2. ATR / price — volatility
        vol_pct = _atr_pct(highs_arr, lows_arr, closes_arr, period=14)

        # 3. EMA slope — trend direction
        ema20 = _ema(closes_arr, 20)
        ema50 = _ema(closes_arr, 50)

        # Slope of EMA(20) over last 5 bars
        ema20_slope = float(ema20[-1] - ema20[-6]) / max(float(ema20[-6]), 1e-10) if n > 5 else 0.0
        price_above_ema50 = float(closes_arr[-1]) > float(ema50[-1])

        # 4. Bollinger Band width
        bb_width = _bollinger_band_width(closes_arr, period=20)

        # Regime classification
        if vol_pct > 3.0:
            regime = "volatile"
        elif adx_val > 25.0 and ema20_slope > 0:
            regime = "trending_up"
        elif adx_val > 25.0 and ema20_slope <= 0:
            regime = "trending_down"
        elif adx_val < 20.0 and vol_pct < 2.0:
            regime = "ranging"
        else:
            # Intermediate zone — use EMA relationship
            if ema20_slope > 0 and price_above_ema50:
                regime = "trending_up"
            elif ema20_slope < 0 and not price_above_ema50:
                regime = "trending_down"
            else:
                regime = "ranging"

        # Confidence calculation
        confidence = _compute_confidence(regime, adx_val, vol_pct, ema20_slope, bb_width)

        # Trend direction: positive = up, negative = down
        trend_direction = ema20_slope * 100  # scale for readability

        details = {
            "ema20_slope": round(ema20_slope * 100, 4),
            "ema20_latest": round(float(ema20[-1]), 4),
            "ema50_latest": round(float(ema50[-1]), 4),
            "bb_width": round(bb_width, 4),
            "price_above_ema50": price_above_ema50,
            "candle_count": n,
        }

        logger.info(
            "regime_detected",
            regime=regime,
            adx=round(adx_val, 2),
            volatility=round(vol_pct, 2),
            confidence=round(confidence, 2),
        )

        return RegimeResult(
            regime=regime,
            confidence=round(confidence, 4),
            adx=round(adx_val, 4),
            volatility=round(vol_pct, 4),
            trend_direction=round(trend_direction, 4),
            details=details,
        )


def _compute_confidence(
    regime: str,
    adx: float,
    vol_pct: float,
    ema_slope: float,
    bb_width: float,
) -> float:
    """Compute a confidence score 0.0-1.0 for the detected regime."""
    if regime == "trending_up":
        # Higher ADX + positive slope = higher confidence
        adx_conf = min(adx / 50.0, 1.0)
        slope_conf = min(abs(ema_slope) * 50, 1.0)
        return 0.6 * adx_conf + 0.4 * slope_conf

    if regime == "trending_down":
        adx_conf = min(adx / 50.0, 1.0)
        slope_conf = min(abs(ema_slope) * 50, 1.0)
        return 0.6 * adx_conf + 0.4 * slope_conf

    if regime == "volatile":
        # Higher vol_pct = higher confidence
        return min(vol_pct / 6.0, 1.0)

    # ranging
    adx_conf = max(1.0 - adx / 30.0, 0.0)
    vol_conf = max(1.0 - vol_pct / 3.0, 0.0)
    bb_conf = max(1.0 - bb_width / 10.0, 0.0)
    return 0.4 * adx_conf + 0.3 * vol_conf + 0.3 * bb_conf
