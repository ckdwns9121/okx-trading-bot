"""Shared technical indicator calculations for use across strategies.

All functions accept numpy arrays (oldest-first ordering).
"""

from __future__ import annotations

import numpy as np


def compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI using Wilder's smoothed moving average and return the latest value.

    Parameters
    ----------
    closes : np.ndarray
        Close price series (oldest first). Must have at least ``period + 1`` elements.
    period : int
        RSI lookback period (default 14).

    Returns
    -------
    float
        Latest RSI value in the range [0, 100]. Returns 50.0 when there is
        insufficient data.
    """
    if len(closes) < period + 1:
        return 50.0  # Not enough data — neutral

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed with simple average over the first period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # Wilder smoothing over remaining bars
    for g, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """Compute Average True Range and return the latest value.

    Uses Wilder's smoothing (alpha = 1/period).

    Parameters
    ----------
    highs : np.ndarray
        High prices (oldest first).
    lows : np.ndarray
        Low prices (oldest first).
    closes : np.ndarray
        Close prices (oldest first). Must have at least ``period + 1`` elements.
    period : int
        ATR period (default 14).

    Returns
    -------
    float
        Latest ATR value. Returns 0.0 when there is insufficient data.
    """
    if len(closes) < period + 1:
        return 0.0

    prev_close = closes[:-1]
    h = highs[1:]
    lo = lows[1:]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_close), np.abs(lo - prev_close)))

    # Wilder smoothing
    result = np.empty_like(tr, dtype=float)
    if len(tr) < period:
        return float(np.mean(tr))
    result[:period] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, len(tr)):
        result[i] = result[i - 1] * (1 - alpha) + tr[i] * alpha

    return float(result[-1])
