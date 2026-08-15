"""Shared pure indicator functions for strategy modules.

Every function returns a list aligned index-for-index with its input;
positions without enough history hold ``None``. No I/O, no state.
"""

from __future__ import annotations

import math
from typing import Sequence


def ema(values: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    multiplier = 2.0 / (period + 1)
    prev = seed
    for index in range(period, len(values)):
        prev = (values[index] - prev) * multiplier + prev
        out[index] = prev
    return out


def rsi_wilder(closes: Sequence[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out

    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        delta = closes[index] - closes[index - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)

    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[index] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def atr_wilder(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    length = len(closes)
    if not (len(highs) == len(lows) == length):
        raise ValueError("highs/lows/closes must be equal length")
    out: list[float | None] = [None] * length
    if length <= period:
        return out

    true_ranges: list[float] = [0.0] * length
    true_ranges[0] = highs[0] - lows[0]
    for index in range(1, length):
        true_ranges[index] = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )

    atr = sum(true_ranges[1 : period + 1]) / period
    out[period] = atr
    for index in range(period + 1, length):
        atr = (atr * (period - 1) + true_ranges[index]) / period
        out[index] = atr
    return out


def bollinger_bands(
    closes: Sequence[float],
    period: int = 20,
    stddev_mult: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (middle, upper, lower) using population standard deviation."""

    if period <= 0:
        raise ValueError("period must be positive")
    middle: list[float | None] = [None] * len(closes)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for index in range(period - 1, len(closes)):
        window = closes[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        band = stddev_mult * math.sqrt(variance)
        middle[index] = mean
        upper[index] = mean + band
        lower[index] = mean - band
    return middle, upper, lower
