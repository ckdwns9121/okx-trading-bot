"""Jesse Livermore inspired trading strategy.

Core principles:
  1. Pivot Point Breakout — enter on N-period high/low breakout with volume confirmation
  2. Trend Filter — only trade in direction of the larger trend (EMA slope)
  3. Pyramiding — add to winning positions (up to max_pyramids times)
  4. Trailing Stop — lock in profits as price moves in our favor
  5. Quick Cut — exit immediately if price reverses past stop level
"""

import numpy as np

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class LivermoreStrategy(BaseStrategy):
    """Jesse Livermore pivot-point breakout with pyramiding and trailing stop.

    Signals:
      - LONG  when price breaks above N-period high, volume confirms, and trend is up
      - SHORT when price breaks below N-period low, volume confirms, and trend is down
      - CLOSE when trailing stop is hit or trend reverses
      - HOLD  otherwise

    Pyramiding: If already in a winning position and a new breakout occurs in the
    same direction, signals another entry with reduced size (size_pct decreases).
    """

    name = "livermore"

    def __init__(self) -> None:
        # Pivot / breakout
        self._pivot_period: int = 20
        self._volume_factor: float = 1.3  # volume must be N× above average

        # Trend filter
        self._trend_ema_period: int = 50

        # Pyramiding
        self._max_pyramids: int = 3
        self._pyramid_count: int = 0
        self._pyramid_size_decay: float = 0.5  # each pyramid is 50% of previous

        # Trailing stop
        self._initial_stop_pct: float = 0.03  # 3% initial stop
        self._trail_step_pct: float = 0.015   # tighten stop by 1.5% per breakout level
        self._current_stop: float = 0.0
        self._highest_since_entry: float = 0.0
        self._lowest_since_entry: float = float("inf")

    @property
    def lookback_period(self) -> int:
        return max(self._pivot_period, self._trend_ema_period) + 2

    def configure(self, params: dict) -> None:
        if "pivot_period" in params:
            v = int(params["pivot_period"])
            if v < 5:
                raise ValueError("pivot_period must be >= 5")
            self._pivot_period = v
        if "volume_factor" in params:
            self._volume_factor = float(params["volume_factor"])
        if "trend_ema_period" in params:
            v = int(params["trend_ema_period"])
            if v < 10:
                raise ValueError("trend_ema_period must be >= 10")
            self._trend_ema_period = v
        if "max_pyramids" in params:
            self._max_pyramids = int(params["max_pyramids"])
        if "initial_stop_pct" in params:
            self._initial_stop_pct = float(params["initial_stop_pct"])
        if "trail_step_pct" in params:
            self._trail_step_pct = float(params["trail_step_pct"])

        logger.info(
            "livermore_configured",
            pivot_period=self._pivot_period,
            volume_factor=self._volume_factor,
            trend_ema=self._trend_ema_period,
            max_pyramids=self._max_pyramids,
            initial_stop=self._initial_stop_pct,
            trail_step=self._trail_step_pct,
        )

    async def on_start(self) -> None:
        self._pyramid_count = 0
        self._current_stop = 0.0
        self._highest_since_entry = 0.0
        self._lowest_since_entry = float("inf")

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _compute_ema(self, values: np.ndarray, period: int) -> np.ndarray:
        """Simple EMA via exponential weights."""
        alpha = 2.0 / (period + 1)
        ema = np.empty_like(values)
        ema[0] = values[0]
        for i in range(1, len(values)):
            ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _is_trend_up(self, closes: np.ndarray) -> bool:
        """Trend is up if EMA is rising over last 3 bars."""
        ema = self._compute_ema(closes, self._trend_ema_period)
        if len(ema) < 3:
            return False
        return ema[-1] > ema[-3]

    def _is_trend_down(self, closes: np.ndarray) -> bool:
        """Trend is down if EMA is falling over last 3 bars."""
        ema = self._compute_ema(closes, self._trend_ema_period)
        if len(ema) < 3:
            return False
        return ema[-1] < ema[-3]

    def _volume_confirmed(self, volumes: np.ndarray) -> bool:
        """Current volume exceeds average by volume_factor."""
        if len(volumes) < self._pivot_period + 1:
            return False
        avg_vol = float(np.mean(volumes[-(self._pivot_period + 1):-1]))
        if avg_vol <= 0:
            return False
        return float(volumes[-1]) > avg_vol * self._volume_factor

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
        required = max(self._pivot_period, self._trend_ema_period) + 2

        if len(all_candles) < required:
            return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason="insufficient_history")

        closes = np.array([c["close"] for c in all_candles], dtype=float)
        highs = np.array([c["high"] for c in all_candles], dtype=float)
        lows = np.array([c["low"] for c in all_candles], dtype=float)
        volumes = np.array([c["volume"] for c in all_candles], dtype=float)

        price = float(candle["close"])
        high = float(candle["high"])
        low = float(candle["low"])

        # Pivot levels (N-period high/low excluding current bar)
        prior_highs = highs[-(self._pivot_period + 1):-1]
        prior_lows = lows[-(self._pivot_period + 1):-1]
        pivot_high = float(np.max(prior_highs))
        pivot_low = float(np.min(prior_lows))

        # Trend
        trend_up = self._is_trend_up(closes)
        trend_down = self._is_trend_down(closes)

        # Volume
        vol_ok = self._volume_confirmed(volumes)

        position = context.current_position
        is_long = position is not None and position.get("direction") == "buy"
        is_short = position is not None and position.get("direction") == "sell"
        in_position = is_long or is_short

        # ── Trailing stop management ──────────────────────────
        if is_long:
            self._highest_since_entry = max(self._highest_since_entry, high)
            trailing_stop = self._highest_since_entry * (1 - self._current_stop)
            if low <= trailing_stop:
                self._pyramid_count = 0
                self._current_stop = 0.0
                self._highest_since_entry = 0.0
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"trailing_stop_hit price={price:.4f} stop={trailing_stop:.4f}",
                )
            # Trend reversal exit
            if trend_down:
                self._pyramid_count = 0
                self._current_stop = 0.0
                self._highest_since_entry = 0.0
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"trend_reversal_exit ema_falling",
                )

        if is_short:
            self._lowest_since_entry = min(self._lowest_since_entry, low)
            trailing_stop = self._lowest_since_entry * (1 + self._current_stop)
            if high >= trailing_stop:
                self._pyramid_count = 0
                self._current_stop = 0.0
                self._lowest_since_entry = float("inf")
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"trailing_stop_hit price={price:.4f} stop={trailing_stop:.4f}",
                )
            if trend_up:
                self._pyramid_count = 0
                self._current_stop = 0.0
                self._lowest_since_entry = float("inf")
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"trend_reversal_exit ema_rising",
                )

        # ── Breakout detection ────────────────────────────────
        breakout_long = price > pivot_high and trend_up and vol_ok
        breakout_short = price < pivot_low and trend_down and vol_ok

        # ── Pyramiding (add to winner) ────────────────────────
        if is_long and breakout_long and self._pyramid_count < self._max_pyramids:
            entry_price = position.get("entry_price", price)
            if price > entry_price:  # only pyramid if in profit
                self._pyramid_count += 1
                # Tighten trailing stop with each pyramid
                self._current_stop = self._initial_stop_pct - (self._trail_step_pct * self._pyramid_count)
                self._current_stop = max(self._current_stop, self._trail_step_pct)  # floor
                size = 100.0 * (self._pyramid_size_decay ** self._pyramid_count)
                logger.info("livermore_pyramid_long", count=self._pyramid_count, size_pct=size)
                return TradeSignal(
                    signal=Signal.LONG,
                    pair=context.pair,
                    leverage=context.leverage,
                    size_pct=size,
                    reason=f"pyramid_{self._pyramid_count} price={price:.4f} pivot={pivot_high:.4f}",
                )

        if is_short and breakout_short and self._pyramid_count < self._max_pyramids:
            entry_price = position.get("entry_price", price)
            if price < entry_price:
                self._pyramid_count += 1
                self._current_stop = self._initial_stop_pct - (self._trail_step_pct * self._pyramid_count)
                self._current_stop = max(self._current_stop, self._trail_step_pct)
                size = 100.0 * (self._pyramid_size_decay ** self._pyramid_count)
                logger.info("livermore_pyramid_short", count=self._pyramid_count, size_pct=size)
                return TradeSignal(
                    signal=Signal.SHORT,
                    pair=context.pair,
                    leverage=context.leverage,
                    size_pct=size,
                    reason=f"pyramid_{self._pyramid_count} price={price:.4f} pivot={pivot_low:.4f}",
                )

        # ── New entry (no position) ───────────────────────────
        if not in_position:
            if breakout_long:
                self._pyramid_count = 0
                self._current_stop = self._initial_stop_pct
                self._highest_since_entry = high
                self._lowest_since_entry = float("inf")
                logger.info("livermore_entry_long", price=price, pivot=pivot_high)
                return TradeSignal(
                    signal=Signal.LONG,
                    pair=context.pair,
                    leverage=context.leverage,
                    reason=f"pivot_breakout_long price={price:.4f} pivot={pivot_high:.4f} vol_confirmed",
                )

            if breakout_short:
                self._pyramid_count = 0
                self._current_stop = self._initial_stop_pct
                self._highest_since_entry = 0.0
                self._lowest_since_entry = low
                logger.info("livermore_entry_short", price=price, pivot=pivot_low)
                return TradeSignal(
                    signal=Signal.SHORT,
                    pair=context.pair,
                    leverage=context.leverage,
                    reason=f"pivot_breakout_short price={price:.4f} pivot={pivot_low:.4f} vol_confirmed",
                )

        logger.debug(
            "livermore_hold",
            pair=context.pair,
            price=round(price, 4),
            pivot_high=round(pivot_high, 4),
            pivot_low=round(pivot_low, 4),
            trend_up=trend_up,
            trend_down=trend_down,
            vol_ok=vol_ok,
        )

        return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason="no_signal")
