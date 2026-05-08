import numpy as np

from app.core.indicators import compute_atr
from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class SevenDayMA5mStrategy(BaseStrategy):
    """5-minute 7-day SMA trend strategy.

    The default moving-average window is 2016 candles:
      7 days * 24 hours * 12 five-minute candles per hour.

    Signals:
      - HOLD  when a close first crosses the 7-day SMA; this arms a pending entry.
      - LONG  on the next confirmed candle if price still holds above the 7-day SMA
              and the trend / Bollinger Band filters pass.
      - SHORT on the next confirmed candle after a bearish cross only when
              direction_mode is "both" or "short".
      - CLOSE when price reaches the relevant Bollinger Band take-profit area
              or an existing position loses its side of the 7-day SMA.
      - HOLD  otherwise.

    Configure this strategy on a 5m timeframe for the default period to represent
    a true 7-day moving average.
    """

    name = "ma_7d_5m"

    def __init__(self) -> None:
        self._ma_period: int = 2016
        self._slope_lookback: int = 4
        self._min_slope_pct: float = 0.0
        self._min_distance_pct: float = 0.0
        self._direction_mode: str = "long"
        self._pending_breakout: str | None = None
        self._bb_period: int = 20
        self._bb_std: float = 2.0
        self._min_bb_width_pct: float = 0.5
        self._min_bb_room_pct: float = 0.2
        self._bb_filter_enabled: bool = True
        self._bb_take_profit_enabled: bool = True

        # Optional risk overlay. Defaults keep all-in sizing, while Bollinger
        # Bands provide a dynamic take-profit reference.
        self._size_pct: float = 100.0
        self._atr_period: int = 14
        self._tp_atr_mult: float | None = None
        self._sl_atr_mult: float | None = None
        self._trailing_stop_pct: float | None = None

    @property
    def lookback_period(self) -> int:
        return max(
            self._ma_period + self._slope_lookback,
            self._bb_period,
            self._atr_period + 1,
        )

    def configure(self, params: dict) -> None:
        """Accept optional overrides for MA/BB filters, direction, sizing and exits."""
        if "ma_period" in params:
            period = int(params["ma_period"])
            if period <= 1:
                raise ValueError("ma_period must be greater than 1")
            self._ma_period = period
        if "slope_lookback" in params:
            lookback = int(params["slope_lookback"])
            if lookback <= 0:
                raise ValueError("slope_lookback must be a positive integer")
            self._slope_lookback = lookback
        if "min_slope_pct" in params:
            self._min_slope_pct = self._non_negative_float(params["min_slope_pct"], "min_slope_pct")
        if "min_distance_pct" in params:
            self._min_distance_pct = self._non_negative_float(params["min_distance_pct"], "min_distance_pct")
        if "direction_mode" in params:
            direction_mode = str(params["direction_mode"])
            if direction_mode not in ("both", "long", "short"):
                raise ValueError("direction_mode must be one of: both, long, short")
            self._direction_mode = direction_mode
        if "bb_period" in params:
            period = int(params["bb_period"])
            if period <= 1:
                raise ValueError("bb_period must be greater than 1")
            self._bb_period = period
        if "bb_std" in params:
            self._bb_std = self._optional_positive_float(params["bb_std"], "bb_std") or self._bb_std
        if "min_bb_width_pct" in params:
            self._min_bb_width_pct = self._non_negative_float(params["min_bb_width_pct"], "min_bb_width_pct")
        if "min_bb_room_pct" in params:
            self._min_bb_room_pct = self._non_negative_float(params["min_bb_room_pct"], "min_bb_room_pct")
        if "bb_filter_enabled" in params:
            self._bb_filter_enabled = self._bool_param(params["bb_filter_enabled"])
        if "bb_take_profit_enabled" in params:
            self._bb_take_profit_enabled = self._bool_param(params["bb_take_profit_enabled"])

        risk_profile = params.get("risk_profile")
        if risk_profile not in (None, "default", "limited"):
            raise ValueError("risk_profile must be one of: default, limited")
        if risk_profile == "default":
            self._apply_default_risk_profile()
        elif risk_profile == "limited":
            self._apply_limited_risk_profile()

        if "size_pct" in params:
            self._size_pct = float(params["size_pct"])
        if "atr_period" in params:
            period = int(params["atr_period"])
            if period <= 0:
                raise ValueError("atr_period must be a positive integer")
            self._atr_period = period
        if "tp_atr_mult" in params:
            self._tp_atr_mult = self._optional_positive_float(params["tp_atr_mult"], "tp_atr_mult")
        if "sl_atr_mult" in params:
            self._sl_atr_mult = self._optional_positive_float(params["sl_atr_mult"], "sl_atr_mult")
        if "trailing_stop_pct" in params:
            self._trailing_stop_pct = self._optional_positive_float(
                params["trailing_stop_pct"],
                "trailing_stop_pct",
            )

        if not 0.0 < self._size_pct <= 100.0:
            raise ValueError("size_pct must be in the range (0, 100]")

        logger.info(
            "ma_7d_5m_configured",
            ma_period=self._ma_period,
            slope_lookback=self._slope_lookback,
            min_slope_pct=self._min_slope_pct,
            min_distance_pct=self._min_distance_pct,
            direction_mode=self._direction_mode,
            pending_breakout=self._pending_breakout,
            bb_period=self._bb_period,
            bb_std=self._bb_std,
            min_bb_width_pct=self._min_bb_width_pct,
            min_bb_room_pct=self._min_bb_room_pct,
            bb_filter_enabled=self._bb_filter_enabled,
            bb_take_profit_enabled=self._bb_take_profit_enabled,
            size_pct=self._size_pct,
            atr_period=self._atr_period,
            tp_atr_mult=self._tp_atr_mult,
            sl_atr_mult=self._sl_atr_mult,
            trailing_stop_pct=self._trailing_stop_pct,
        )

    @staticmethod
    def _optional_positive_float(value: object, name: str) -> float | None:
        if value is None:
            return None
        parsed = float(value)
        if parsed <= 0.0:
            raise ValueError(f"{name} must be positive when provided")
        return parsed

    @staticmethod
    def _non_negative_float(value: object, name: str) -> float:
        parsed = float(value)
        if parsed < 0.0:
            raise ValueError(f"{name} must be non-negative")
        return parsed

    @staticmethod
    def _bool_param(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on", "enabled")

    def _apply_default_risk_profile(self) -> None:
        self._size_pct = 100.0
        self._tp_atr_mult = None
        self._sl_atr_mult = None
        self._trailing_stop_pct = None

    def _apply_limited_risk_profile(self) -> None:
        self._size_pct = 25.0
        self._tp_atr_mult = 2.0
        self._sl_atr_mult = 1.0
        self._trailing_stop_pct = 0.025

    def _sma(self, closes: np.ndarray, end: int | None = None) -> float:
        if end is None:
            end = len(closes)
        start = end - self._ma_period
        return float(np.mean(closes[start:end]))

    def _compute_bollinger_bands(self, closes: np.ndarray) -> tuple[float, float, float]:
        if len(closes) < self._bb_period:
            mid = float(closes[-1])
            return mid, mid, mid

        window = closes[-self._bb_period :]
        middle = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        upper = middle + self._bb_std * std
        lower = middle - self._bb_std * std
        return upper, middle, lower

    def _risk_prices(
        self,
        signal: Signal,
        entry_price: float,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        bb_upper: float | None = None,
        bb_lower: float | None = None,
    ) -> tuple[float | None, float | None]:
        atr = compute_atr(highs, lows, closes, self._atr_period)
        tp_price = None
        sl_price = None
        if signal == Signal.LONG:
            if atr > 0.0 and self._tp_atr_mult is not None:
                tp_price = entry_price + atr * self._tp_atr_mult
            if atr > 0.0 and self._sl_atr_mult is not None:
                sl_price = entry_price - atr * self._sl_atr_mult
            if self._bb_take_profit_enabled and bb_upper is not None and bb_upper > entry_price:
                tp_price = bb_upper if tp_price is None else min(tp_price, bb_upper)
        elif signal == Signal.SHORT:
            if atr > 0.0 and self._tp_atr_mult is not None:
                tp_price = entry_price - atr * self._tp_atr_mult
            if atr > 0.0 and self._sl_atr_mult is not None:
                sl_price = entry_price + atr * self._sl_atr_mult
            if self._bb_take_profit_enabled and bb_lower is not None and bb_lower < entry_price:
                tp_price = bb_lower if tp_price is None else max(tp_price, bb_lower)

        return tp_price, sl_price

    def _build_entry_signal(
        self,
        signal: Signal,
        price: float,
        ma_now: float,
        slope_pct: float,
        distance_pct: float,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        context: TradingContext,
        bb_upper: float,
        bb_lower: float,
    ) -> TradeSignal:
        tp_price, sl_price = self._risk_prices(signal, price, highs, lows, closes, bb_upper, bb_lower)
        side = "long" if signal == Signal.LONG else "short"
        return TradeSignal(
            signal=signal,
            pair=context.pair,
            leverage=context.leverage,
            size_pct=self._size_pct,
            reason=(
                f"{side}_confirmed_after_7d_ma_breakout "
                f"price={price:.4f} ma={ma_now:.4f} "
                f"slope={slope_pct:.4f}% distance={distance_pct:.4f}%"
            ),
            tp_price=tp_price,
            sl_price=sl_price,
            trailing_stop_pct=self._trailing_stop_pct,
        )

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

        if len(closes) < self.lookback_period:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="insufficient_history",
            )

        price = float(candle["close"])
        prev_close = float(closes[-2])
        ma_now = self._sma(closes)
        ma_prev = self._sma(closes, len(closes) - 1)
        ma_slope_anchor = self._sma(closes, len(closes) - self._slope_lookback)
        slope_pct = 0.0 if ma_slope_anchor == 0.0 else (ma_now - ma_slope_anchor) / ma_slope_anchor * 100.0
        distance_pct = 0.0 if ma_now == 0.0 else (price - ma_now) / ma_now * 100.0
        bb_upper, bb_middle, bb_lower = self._compute_bollinger_bands(closes)
        bb_width_pct = 0.0 if bb_middle == 0.0 else (bb_upper - bb_lower) / bb_middle * 100.0
        long_bb_room_pct = 0.0 if price == 0.0 else (bb_upper - price) / price * 100.0
        short_bb_room_pct = 0.0 if price == 0.0 else (price - bb_lower) / price * 100.0

        logger.debug(
            "ma_7d_5m_indicators",
            pair=context.pair,
            price=round(price, 4),
            ma_now=round(ma_now, 4),
            ma_prev=round(ma_prev, 4),
            slope_pct=round(slope_pct, 5),
            distance_pct=round(distance_pct, 5),
            bb_upper=round(bb_upper, 4),
            bb_middle=round(bb_middle, 4),
            bb_lower=round(bb_lower, 4),
            bb_width_pct=round(bb_width_pct, 5),
            long_bb_room_pct=round(long_bb_room_pct, 5),
        )

        crossed_above = prev_close <= ma_prev and price > ma_now
        crossed_below = prev_close >= ma_prev and price < ma_now
        position = context.current_position
        is_long = position is not None and position.get("direction") in ("buy", "long")
        is_short = position is not None and position.get("direction") in ("sell", "short")

        # Live execution opens only when flat, so close the current position
        # before attempting the opposite side on a later signal.
        if is_long and self._bb_take_profit_enabled and price >= bb_upper:
            self._pending_breakout = None
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=(
                    f"bb_upper_take_profit price={price:.4f} bb_upper={bb_upper:.4f} "
                    f"bb_width={bb_width_pct:.3f}%"
                ),
            )
        if is_short and self._bb_take_profit_enabled and price <= bb_lower:
            self._pending_breakout = None
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=(
                    f"bb_lower_take_profit price={price:.4f} bb_lower={bb_lower:.4f} "
                    f"bb_width={bb_width_pct:.3f}%"
                ),
            )
        if is_long and price < ma_now:
            self._pending_breakout = None
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=(
                    f"lost_7d_ma_support price={price:.4f} ma={ma_now:.4f} "
                    f"distance={distance_pct:.3f}%"
                ),
            )
        if is_short and price > ma_now:
            self._pending_breakout = None
            return TradeSignal(
                signal=Signal.CLOSE,
                pair=context.pair,
                reason=(
                    f"reclaimed_7d_ma_resistance price={price:.4f} ma={ma_now:.4f} "
                    f"distance={distance_pct:.3f}%"
                ),
            )

        long_allowed = self._direction_mode in ("both", "long")
        short_allowed = self._direction_mode in ("both", "short")
        long_filter = slope_pct >= self._min_slope_pct and distance_pct >= self._min_distance_pct
        short_filter = slope_pct <= -self._min_slope_pct and -distance_pct >= self._min_distance_pct

        if self._pending_breakout == "long":
            self._pending_breakout = None
            if not long_allowed:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason="pending_long_blocked_by_direction_mode",
                )
            if price <= ma_now:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_long_invalidated price={price:.4f} ma={ma_now:.4f} "
                        f"distance={distance_pct:.4f}%"
                    ),
                )
            if self._bb_filter_enabled and bb_width_pct < self._min_bb_width_pct:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_long_bb_width_blocked width={bb_width_pct:.4f}% "
                        f"min_width={self._min_bb_width_pct:.4f}%"
                    ),
                )
            if self._bb_filter_enabled and (price >= bb_upper or long_bb_room_pct < self._min_bb_room_pct):
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_long_bb_room_blocked room={long_bb_room_pct:.4f}% "
                        f"min_room={self._min_bb_room_pct:.4f}% price={price:.4f} bb_upper={bb_upper:.4f}"
                    ),
                )
            if not long_filter:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_long_filter_blocked slope={slope_pct:.4f}% distance={distance_pct:.4f}% "
                        f"min_slope={self._min_slope_pct:.4f}% min_distance={self._min_distance_pct:.4f}%"
                    ),
                )
            if not is_long:
                return self._build_entry_signal(
                    Signal.LONG,
                    price,
                    ma_now,
                    slope_pct,
                    distance_pct,
                    highs,
                    lows,
                    closes,
                    context,
                    bb_upper,
                    bb_lower,
                )

        if self._pending_breakout == "short":
            self._pending_breakout = None
            if not short_allowed:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason="pending_short_blocked_by_direction_mode",
                )
            if price >= ma_now:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_short_invalidated price={price:.4f} ma={ma_now:.4f} "
                        f"distance={distance_pct:.4f}%"
                    ),
                )
            if self._bb_filter_enabled and bb_width_pct < self._min_bb_width_pct:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_short_bb_width_blocked width={bb_width_pct:.4f}% "
                        f"min_width={self._min_bb_width_pct:.4f}%"
                    ),
                )
            if self._bb_filter_enabled and (price <= bb_lower or short_bb_room_pct < self._min_bb_room_pct):
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_short_bb_room_blocked room={short_bb_room_pct:.4f}% "
                        f"min_room={self._min_bb_room_pct:.4f}% price={price:.4f} bb_lower={bb_lower:.4f}"
                    ),
                )
            if not short_filter:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_short_filter_blocked slope={slope_pct:.4f}% distance={distance_pct:.4f}% "
                        f"min_slope={self._min_slope_pct:.4f}% min_distance={self._min_distance_pct:.4f}%"
                    ),
                )
            if not is_short:
                return self._build_entry_signal(
                    Signal.SHORT,
                    price,
                    ma_now,
                    slope_pct,
                    distance_pct,
                    highs,
                    lows,
                    closes,
                    context,
                    bb_upper,
                    bb_lower,
                )

        if crossed_above:
            if not long_allowed:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason="long_blocked_by_direction_mode",
                )
            if not is_long:
                self._pending_breakout = "long"
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_long_after_7d_ma_breakout price={price:.4f} ma={ma_now:.4f} "
                        f"slope={slope_pct:.4f}% distance={distance_pct:.4f}%"
                    ),
                )

        if crossed_below:
            if not short_allowed:
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason="short_blocked_by_direction_mode",
                )
            if not is_short:
                self._pending_breakout = "short"
                return TradeSignal(
                    signal=Signal.HOLD,
                    pair=context.pair,
                    reason=(
                        f"pending_short_after_7d_ma_breakout price={price:.4f} ma={ma_now:.4f} "
                        f"slope={slope_pct:.4f}% distance={distance_pct:.4f}%"
                    ),
                )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"price={price:.4f} ma={ma_now:.4f} "
                f"slope={slope_pct:.4f}% distance={distance_pct:.4f}%"
            ),
        )
