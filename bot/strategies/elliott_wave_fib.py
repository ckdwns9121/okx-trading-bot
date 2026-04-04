"""Elliott Wave + RSI + Volume + Fibonacci composite trading strategy.

Detects Elliott Wave patterns via swing high/low (ZigZag) detection, then
confirms entries with RSI divergence, volume confirmation, and Fibonacci
retracement levels.  Conservative by design -- multiple confirmations are
required before any entry signal is emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Internal data structures                                            #
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class SwingPoint:
    """A detected swing high or swing low."""

    index: int
    price: float
    kind: Literal["high", "low"]


@dataclass(frozen=True)
class WaveState:
    """Result of the simplified Elliott Wave counter."""

    wave_count: int  # 1-5 (or 0 when undetermined)
    direction: Literal["up", "down", "none"]
    wave_points: list[SwingPoint]


# ------------------------------------------------------------------ #
# Strategy                                                            #
# ------------------------------------------------------------------ #

class ElliottWaveFibStrategy(BaseStrategy):
    """Elliott Wave + RSI + Volume + Fibonacci composite strategy.

    Entry signals require *all* of the following to align:
      - Elliott Wave position (wave 3 entry or wave 5 exhaustion)
      - Fibonacci retracement proximity
      - RSI confirmation (momentum or divergence)
      - Volume confirmation

    This makes the strategy conservative -- it trades infrequently but
    with higher probability setups.
    """

    name = "elliott_wave_fib"

    def __init__(self) -> None:
        self._swing_threshold: float = 2.0  # percent
        self._stop_loss_pct: float = 3.0
        self._max_favorable_pnl: float = 0.0
        self._rsi_period: int = 14
        self._volume_period: int = 20
        self._fib_entry_tolerance: float = 0.02  # 2 %
        self._swing_lookback: int = 5  # bars each side for swing detection

    # ------------------------------------------------------------------ #
    # ABC implementation                                                  #
    # ------------------------------------------------------------------ #

    @property
    def lookback_period(self) -> int:
        return 89  # Fibonacci number -- enough for wave detection + indicators

    def configure(self, params: dict) -> None:
        """Accept optional overrides for strategy parameters."""
        if "swing_threshold" in params:
            self._swing_threshold = float(params["swing_threshold"])
        if "rsi_period" in params:
            period = int(params["rsi_period"])
            if period <= 0:
                raise ValueError("rsi_period must be a positive integer")
            self._rsi_period = period
        if "volume_period" in params:
            period = int(params["volume_period"])
            if period <= 0:
                raise ValueError("volume_period must be a positive integer")
            self._volume_period = period
        if "fib_entry_tolerance" in params:
            self._fib_entry_tolerance = float(params["fib_entry_tolerance"])
        if "stop_loss_pct" in params:
            self._stop_loss_pct = float(params["stop_loss_pct"])
        logger.info(
            "elliott_wave_fib_configured",
            swing_threshold=self._swing_threshold,
            rsi_period=self._rsi_period,
            volume_period=self._volume_period,
            fib_entry_tolerance=self._fib_entry_tolerance,
        )

    # ------------------------------------------------------------------ #
    # Indicator helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_rsi(closes: np.ndarray, period: int) -> float:
        """Wilder-smoothed RSI for the last value in *closes*."""
        if len(closes) < period + 1:
            return 50.0  # neutral fallback

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Seed with SMA then apply Wilder smoothing
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _compute_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
        """Return full RSI series (same length as *closes*; first *period* values = 50)."""
        rsi = np.full(len(closes), 50.0)
        if len(closes) < period + 1:
            return rsi

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        if avg_loss == 0.0:
            rsi[period] = 100.0
        else:
            rsi[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
            if avg_loss == 0.0:
                rsi[i + 1] = 100.0
            else:
                rsi[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        return rsi

    @staticmethod
    def _volume_ratio(volumes: np.ndarray, period: int) -> float:
        """Current volume divided by average of preceding *period* bars."""
        if len(volumes) < 2:
            return 1.0
        lookback = volumes[-period - 1: -1] if len(volumes) > period else volumes[:-1]
        avg = float(np.mean(lookback))
        if avg == 0.0:
            return 1.0
        return float(volumes[-1]) / avg

    # ------------------------------------------------------------------ #
    # Swing / ZigZag detection                                            #
    # ------------------------------------------------------------------ #

    def _find_swings(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        threshold_pct: float,
    ) -> list[SwingPoint]:
        """Identify swing highs and swing lows using a percentage threshold.

        A swing high at index *i* requires ``highs[i]`` to be the highest
        within *self._swing_lookback* bars on each side **and** at least
        *threshold_pct*% above the nearest swing low (and vice-versa).
        """
        n = len(closes)
        lb = self._swing_lookback
        swings: list[SwingPoint] = []

        for i in range(lb, n - lb):
            window_high = highs[i - lb: i + lb + 1]
            window_low = lows[i - lb: i + lb + 1]

            is_swing_high = float(highs[i]) == float(np.max(window_high))
            is_swing_low = float(lows[i]) == float(np.min(window_low))

            if is_swing_high and not is_swing_low:
                # Check threshold vs last swing low
                if swings and swings[-1].kind == "low":
                    pct_change = (float(highs[i]) - swings[-1].price) / swings[-1].price * 100.0
                    if pct_change < threshold_pct:
                        continue
                swings.append(SwingPoint(index=i, price=float(highs[i]), kind="high"))
            elif is_swing_low and not is_swing_high:
                if swings and swings[-1].kind == "high":
                    pct_change = (swings[-1].price - float(lows[i])) / swings[-1].price * 100.0
                    if pct_change < threshold_pct:
                        continue
                swings.append(SwingPoint(index=i, price=float(lows[i]), kind="low"))

        # Remove consecutive same-kind swings (keep the more extreme one)
        filtered: list[SwingPoint] = []
        for sp in swings:
            if filtered and filtered[-1].kind == sp.kind:
                if sp.kind == "high" and sp.price > filtered[-1].price:
                    filtered[-1] = sp
                elif sp.kind == "low" and sp.price < filtered[-1].price:
                    filtered[-1] = sp
            else:
                filtered.append(sp)

        return filtered

    # ------------------------------------------------------------------ #
    # Elliott Wave counter                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _count_waves(swings: list[SwingPoint]) -> WaveState:
        """Simplified Elliott Wave counting from detected swings.

        Counts alternating higher-highs / higher-lows (up) or
        lower-highs / lower-lows (down) to determine current wave position.
        """
        if len(swings) < 3:
            return WaveState(wave_count=0, direction="none", wave_points=[])

        # Determine trend direction from the last several swings.
        # Look at the most recent swings (up to 10) to find the dominant pattern.
        recent = swings[-10:]

        # Check for uptrend pattern: higher highs AND higher lows
        highs_in_order = [s for s in recent if s.kind == "high"]
        lows_in_order = [s for s in recent if s.kind == "low"]

        up_count = 0
        down_count = 0

        # Count consecutive higher-highs
        for i in range(1, len(highs_in_order)):
            if highs_in_order[i].price > highs_in_order[i - 1].price:
                up_count += 1
            else:
                break

        # Count consecutive lower-lows
        for i in range(1, len(lows_in_order)):
            if lows_in_order[i].price < lows_in_order[i - 1].price:
                down_count += 1
            else:
                break

        if up_count >= down_count and up_count >= 1:
            direction: Literal["up", "down", "none"] = "up"
            # Wave count: each swing pair (low->high) = one wave in uptrend
            wave_count = min(up_count + 1, 5)
            wave_points = recent[-(wave_count * 2):] if len(recent) >= wave_count * 2 else recent
        elif down_count > up_count and down_count >= 1:
            direction = "down"
            wave_count = min(down_count + 1, 5)
            wave_points = recent[-(wave_count * 2):] if len(recent) >= wave_count * 2 else recent
        else:
            return WaveState(wave_count=0, direction="none", wave_points=[])

        return WaveState(
            wave_count=wave_count,
            direction=direction,
            wave_points=wave_points,
        )

    # ------------------------------------------------------------------ #
    # Fibonacci levels                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fibonacci_levels(swing_low: float, swing_high: float) -> dict[str, float]:
        """Fibonacci retracement and extension levels between two swing points."""
        diff = swing_high - swing_low
        return {
            "0.236": swing_high - 0.236 * diff,
            "0.382": swing_high - 0.382 * diff,
            "0.500": swing_high - 0.500 * diff,
            "0.618": swing_high - 0.618 * diff,
            "0.786": swing_high - 0.786 * diff,
            "1.000": swing_low,
            "1.618": swing_high + 0.618 * diff,  # extension
        }

    def _nearest_fib_level(
        self,
        price: float,
        fib_levels: dict[str, float],
        tolerance: float,
    ) -> str | None:
        """Return the name of the nearest Fibonacci level within *tolerance*, or ``None``."""
        best_name: str | None = None
        best_dist = float("inf")
        for name, level in fib_levels.items():
            if level == 0.0:
                continue
            dist = abs(price - level) / level
            if dist < tolerance and dist < best_dist:
                best_dist = dist
                best_name = name
        return best_name

    # ------------------------------------------------------------------ #
    # RSI divergence                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_rsi_divergence(
        closes: np.ndarray,
        rsi_values: np.ndarray,
        swings: list[SwingPoint],
    ) -> tuple[bool, float]:
        """Detect bearish RSI divergence (price new high, RSI lower high).

        Returns ``(is_divergent, divergence_magnitude)``.
        """
        swing_highs = [s for s in swings if s.kind == "high"]
        if len(swing_highs) < 2:
            return False, 0.0

        prev_high = swing_highs[-2]
        curr_high = swing_highs[-1]

        # Price made a higher high
        if curr_high.price <= prev_high.price:
            return False, 0.0

        # RSI made a lower high
        prev_rsi = float(rsi_values[prev_high.index]) if prev_high.index < len(rsi_values) else 50.0
        curr_rsi = float(rsi_values[curr_high.index]) if curr_high.index < len(rsi_values) else 50.0

        if curr_rsi < prev_rsi:
            divergence = prev_rsi - curr_rsi
            return True, divergence

        return False, 0.0

    # ------------------------------------------------------------------ #
    # Main signal logic                                                   #
    # ------------------------------------------------------------------ #

    async def on_candle(
        self,
        candle: dict,
        history: list[dict],
        context: TradingContext,
    ) -> TradeSignal:
        all_candles = history + [candle]

        if len(all_candles) < self.lookback_period:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        # ----- Extract arrays -----
        closes = np.array([c["close"] for c in all_candles], dtype=float)
        highs = np.array([c["high"] for c in all_candles], dtype=float)
        lows = np.array([c["low"] for c in all_candles], dtype=float)
        volumes = np.array([c["volume"] for c in all_candles], dtype=float)
        price = float(candle["close"])

        # ----- Compute indicators -----
        rsi = self._compute_rsi(closes, self._rsi_period)
        rsi_series = self._compute_rsi_series(closes, self._rsi_period)
        vol_ratio = self._volume_ratio(volumes, self._volume_period)

        # ----- Swing detection & wave counting -----
        swings = self._find_swings(closes, highs, lows, self._swing_threshold)
        wave = self._count_waves(swings)

        # ----- Fibonacci levels from the most recent completed impulse -----
        fib_levels: dict[str, float] = {}
        nearest_fib: str | None = None
        impulse_low = 0.0
        impulse_high = 0.0

        if len(swings) >= 2:
            swing_highs = [s for s in swings if s.kind == "high"]
            swing_lows = [s for s in swings if s.kind == "low"]
            if swing_highs and swing_lows:
                impulse_high = max(s.price for s in swing_highs[-3:]) if swing_highs else price
                impulse_low = min(s.price for s in swing_lows[-3:]) if swing_lows else price
                if impulse_high > impulse_low:
                    fib_levels = self._fibonacci_levels(impulse_low, impulse_high)
                    nearest_fib = self._nearest_fib_level(price, fib_levels, self._fib_entry_tolerance)

        # ----- RSI divergence -----
        has_divergence, div_magnitude = self._detect_rsi_divergence(closes, rsi_series, swings)

        # ----- Debug logging -----
        logger.debug(
            "elliott_wave_fib_state",
            pair=context.pair,
            price=round(price, 4),
            wave_count=wave.wave_count,
            wave_dir=wave.direction,
            rsi=round(rsi, 1),
            vol_ratio=round(vol_ratio, 2),
            nearest_fib=nearest_fib or "none",
            rsi_divergence=has_divergence,
            num_swings=len(swings),
        )

        # ----- Position state -----
        position = context.current_position
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"

        # ----- Trailing stop: track max favorable PnL -----
        if position is not None:
            unrealized_pnl = position.get("unrealized_pnl", 0.0)
            self._max_favorable_pnl = max(self._max_favorable_pnl, unrealized_pnl)
            if (
                self._max_favorable_pnl > 0
                and unrealized_pnl < self._max_favorable_pnl * 0.5
            ):
                peak = self._max_favorable_pnl
                self._max_favorable_pnl = 0.0
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=(
                        f"trailing_stop_gave_back_50pct "
                        f"peak_pnl={peak:.4f} "
                        f"current_pnl={unrealized_pnl:.4f}"
                    ),
                )
        else:
            self._max_favorable_pnl = 0.0

        # ============================================================== #
        # CLOSE signals                                                   #
        # ============================================================== #
        if is_long:
            # Close long: RSI overbought OR fib extension 1.618 hit OR wave 5 detected
            if rsi > 75.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"long_exit_rsi_overbought rsi={rsi:.1f}",
                )
            if fib_levels and price >= fib_levels.get("1.618", float("inf")):
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"long_exit_fib_extension price={price:.4f} fib_1.618={fib_levels['1.618']:.4f}",
                )
            if wave.direction == "up" and wave.wave_count >= 5:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"long_exit_wave5_complete wave={wave.wave_count}",
                )

        if is_short:
            # Close short: RSI oversold OR price at fib 0.786 support
            if rsi < 25.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"short_exit_rsi_oversold rsi={rsi:.1f}",
                )
            if fib_levels and price <= fib_levels.get("0.786", 0.0):
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"short_exit_fib_support price={price:.4f} fib_0.786={fib_levels['0.786']:.4f}",
                )

        # ============================================================== #
        # ENTRY signals                                                   #
        # ============================================================== #

        # --- LONG: Wave 3 Ride ---
        long_wave3 = (
            wave.direction == "up"
            and wave.wave_count in (2, 3)
            and nearest_fib in ("0.382", "0.618")
            and 30.0 <= rsi <= 65.0
            and vol_ratio > 1.0
        )
        if long_wave3 and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"wave3_entry wave={wave.wave_count} "
                    f"rsi={rsi:.1f} fib={nearest_fib} vol_ratio={vol_ratio:.1f}"
                ),
            )

        # --- LONG: Correction Buy ---
        correction_buy = (
            wave.direction == "up"
            and wave.wave_count >= 5
            and nearest_fib in ("0.500", "0.618")
            and rsi < 40.0
            and vol_ratio < 1.0
        )
        if correction_buy and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                reason=f"correction_buy fib={nearest_fib} rsi={rsi:.1f}",
            )

        # --- SHORT: Wave 5 Exhaustion ---
        wave5_exhaustion = (
            wave.direction == "up"
            and wave.wave_count >= 5
            and has_divergence
            and vol_ratio < 1.0
        )
        if wave5_exhaustion and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"wave5_exhaustion rsi_div={div_magnitude:.1f} "
                    f"vol_decline={vol_ratio:.1f}"
                ),
            )

        # --- SHORT: Wave 3 Down ---
        short_wave3 = (
            wave.direction == "down"
            and wave.wave_count in (2, 3)
            and nearest_fib in ("0.382", "0.618")
            and 40.0 <= rsi <= 65.0
            and vol_ratio > 1.0
        )
        if short_wave3 and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                reason=(
                    f"wave3_down wave={wave.wave_count} "
                    f"rsi={rsi:.1f} fib={nearest_fib} vol_ratio={vol_ratio:.1f}"
                ),
            )

        # ============================================================== #
        # Default HOLD                                                    #
        # ============================================================== #
        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"wave={wave.wave_count}/{wave.direction} "
                f"rsi={rsi:.1f} vol_ratio={vol_ratio:.2f} fib={nearest_fib or 'none'}"
            ),
        )
