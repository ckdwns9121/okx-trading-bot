"""ICT-inspired Liquidity Sweep + MSS + FVG retest strategy.

This is a deterministic, backtest-friendly interpretation of a narrow ICT setup:
liquidity sweep -> market structure shift -> fair value gap -> retest entry.
It intentionally avoids discretionary ICT concepts that cannot be verified from
closed OHLCV candles. Optional quality filters can require trend alignment,
active UTC session hours, sufficient volatility, and directional retest candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)

Direction = Literal["bullish", "bearish"]
SetupState = Literal["swept", "mss_confirmed", "waiting_retest"]


@dataclass
class _Setup:
    direction: Direction
    state: SetupState
    sweep_level: float
    sweep_extreme: float
    mss_level: float
    bars_since_sweep: int = 0
    bars_since_mss: int = 0
    bars_since_fvg: int = 0
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None


class ICTLiquidityFVGStrategy(BaseStrategy):
    """Liquidity sweep + MSS + FVG retest strategy.

    Bullish model:
      1. Current candle sweeps below the recent lookback low and closes back above it.
      2. A later candle closes above a recent swing high (MSS).
      3. A bullish three-candle FVG appears: candle[-3].high < candle[-1].low.
      4. Price retests the FVG and emits LONG with SL below the sweep low and TP by RR.

    Bearish model mirrors the bullish path.
    """

    name = "ict_liquidity_fvg"

    def __init__(self) -> None:
        self._direction_mode = "both"
        self._sweep_lookback = 20
        self._mss_lookback = 5
        self._mss_max_bars = 10
        self._fvg_max_bars = 10
        self._retest_max_bars = 10
        self._min_sweep_pct = 0.0
        self._min_fvg_pct = 0.02
        self._sl_buffer_pct = 0.03
        self._reward_risk = 2.0
        self._size_pct = 10.0
        self._cooldown_bars = 3
        self._trend_filter_mode = "off"
        self._trend_lookback = 96
        self._min_trend_slope_pct = 0.0
        self._session_filter_mode = "off"
        self._session_start_hour_utc = 7
        self._session_end_hour_utc = 20
        self._atr_period = 14
        self._min_atr_pct = 0.0
        self._max_atr_pct = 100.0
        self._min_mss_body_pct = 0.0
        self._min_mss_displacement_pct = 0.0
        self._retest_confirmation = "off"

        self._cooldown_remaining = 0
        self._setup: Optional[_Setup] = None

    @property
    def lookback_period(self) -> int:
        sweep = int(getattr(self, "_sweep_lookback", 20))
        mss = int(getattr(self, "_mss_lookback", 5))
        required = max(sweep + mss + 3, 10)
        if getattr(self, "_trend_filter_mode", "off") == "ema":
            trend = int(getattr(self, "_trend_lookback", 96))
            slope_extra = 1 if getattr(self, "_min_trend_slope_pct", 0.0) > 0 else 0
            required = max(required, trend + slope_extra)
        if self._atr_filter_enabled:
            required = max(required, int(getattr(self, "_atr_period", 14)) + 1)
        return required

    @property
    def _required_history(self) -> int:
        required = self._sweep_lookback
        if self._trend_filter_mode == "ema":
            required = max(required, self._trend_lookback)
            if self._min_trend_slope_pct > 0:
                required += 1
        if self._atr_filter_enabled:
            required = max(required, self._atr_period + 1)
        return required

    @property
    def _atr_filter_enabled(self) -> bool:
        return self._min_atr_pct > 0 or self._max_atr_pct < 100.0

    def configure(self, params: dict) -> None:
        self._direction_mode = self._choice(
            params.get("direction_mode", self._direction_mode),
            "direction_mode",
            {"both", "long", "short"},
        )
        self._sweep_lookback = self._positive_int(
            params.get("sweep_lookback", self._sweep_lookback), "sweep_lookback"
        )
        self._mss_lookback = self._positive_int(
            params.get("mss_lookback", self._mss_lookback), "mss_lookback"
        )
        self._mss_max_bars = self._positive_int(
            params.get("mss_max_bars", self._mss_max_bars), "mss_max_bars"
        )
        self._fvg_max_bars = self._positive_int(
            params.get("fvg_max_bars", self._fvg_max_bars), "fvg_max_bars"
        )
        self._retest_max_bars = self._positive_int(
            params.get("retest_max_bars", self._retest_max_bars), "retest_max_bars"
        )
        self._cooldown_bars = self._non_negative_int(
            params.get("cooldown_bars", self._cooldown_bars), "cooldown_bars"
        )
        self._min_sweep_pct = self._non_negative_float(
            params.get("min_sweep_pct", self._min_sweep_pct), "min_sweep_pct"
        )
        self._min_fvg_pct = self._non_negative_float(
            params.get("min_fvg_pct", self._min_fvg_pct), "min_fvg_pct"
        )
        self._sl_buffer_pct = self._non_negative_float(
            params.get("sl_buffer_pct", self._sl_buffer_pct), "sl_buffer_pct"
        )
        self._reward_risk = self._positive_float(params.get("reward_risk", self._reward_risk), "reward_risk")
        self._size_pct = self._bounded_float(params.get("size_pct", self._size_pct), "size_pct", 0.0, 100.0)
        self._trend_filter_mode = self._choice(
            params.get("trend_filter_mode", self._trend_filter_mode),
            "trend_filter_mode",
            {"off", "ema"},
        )
        self._trend_lookback = self._positive_int(
            params.get("trend_lookback", self._trend_lookback), "trend_lookback"
        )
        self._min_trend_slope_pct = self._non_negative_float(
            params.get("min_trend_slope_pct", self._min_trend_slope_pct),
            "min_trend_slope_pct",
        )
        self._session_filter_mode = self._choice(
            params.get("session_filter_mode", self._session_filter_mode),
            "session_filter_mode",
            {"off", "utc"},
        )
        self._session_start_hour_utc = self._bounded_int(
            params.get("session_start_hour_utc", self._session_start_hour_utc),
            "session_start_hour_utc",
            0,
            23,
        )
        self._session_end_hour_utc = self._bounded_int(
            params.get("session_end_hour_utc", self._session_end_hour_utc),
            "session_end_hour_utc",
            0,
            24,
        )
        self._atr_period = self._positive_int(params.get("atr_period", self._atr_period), "atr_period")
        self._min_atr_pct = self._non_negative_float(
            params.get("min_atr_pct", self._min_atr_pct), "min_atr_pct"
        )
        self._max_atr_pct = self._positive_float(
            params.get("max_atr_pct", self._max_atr_pct), "max_atr_pct"
        )
        if self._max_atr_pct < self._min_atr_pct:
            raise ValueError("max_atr_pct must be >= min_atr_pct")
        self._min_mss_body_pct = self._non_negative_float(
            params.get("min_mss_body_pct", self._min_mss_body_pct),
            "min_mss_body_pct",
        )
        self._min_mss_displacement_pct = self._non_negative_float(
            params.get("min_mss_displacement_pct", self._min_mss_displacement_pct),
            "min_mss_displacement_pct",
        )
        self._retest_confirmation = self._choice(
            params.get("retest_confirmation", self._retest_confirmation),
            "retest_confirmation",
            {"off", "directional_close"},
        )

        logger.info(
            "ict_liquidity_fvg_configured",
            direction_mode=self._direction_mode,
            sweep_lookback=self._sweep_lookback,
            mss_lookback=self._mss_lookback,
            mss_max_bars=self._mss_max_bars,
            fvg_max_bars=self._fvg_max_bars,
            retest_max_bars=self._retest_max_bars,
            min_sweep_pct=self._min_sweep_pct,
            min_fvg_pct=self._min_fvg_pct,
            sl_buffer_pct=self._sl_buffer_pct,
            reward_risk=self._reward_risk,
            size_pct=self._size_pct,
            cooldown_bars=self._cooldown_bars,
            trend_filter_mode=self._trend_filter_mode,
            trend_lookback=self._trend_lookback,
            min_trend_slope_pct=self._min_trend_slope_pct,
            session_filter_mode=self._session_filter_mode,
            session_start_hour_utc=self._session_start_hour_utc,
            session_end_hour_utc=self._session_end_hour_utc,
            atr_period=self._atr_period,
            min_atr_pct=self._min_atr_pct,
            max_atr_pct=self._max_atr_pct,
            min_mss_body_pct=self._min_mss_body_pct,
            min_mss_displacement_pct=self._min_mss_displacement_pct,
            retest_confirmation=self._retest_confirmation,
        )

    async def on_candle(
        self,
        candle: dict,
        history: list[dict],
        context: TradingContext,
    ) -> TradeSignal:
        pair = context.pair

        if len(history) < self._required_history:
            return self._hold(pair, "insufficient_history")

        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return self._hold(pair, f"cooldown bars_remaining={self._cooldown_remaining}")

        all_candles = history + [candle]

        if self._setup is not None:
            signal = self._advance_setup(candle, all_candles, context)
            if signal is not None:
                return signal

        if self._setup is None:
            self._setup = self._detect_sweep(candle, history)
            if self._setup is not None:
                return self._hold(
                    pair,
                    (
                        f"{self._setup.direction}_sweep_detected "
                        f"sweep_level={self._setup.sweep_level:.6f} "
                        f"extreme={self._setup.sweep_extreme:.6f} mss={self._setup.mss_level:.6f}"
                    ),
                )

        if self._setup is not None:
            return self._hold(
                pair,
                f"ict_setup_state={self._setup.direction}:{self._setup.state}",
            )
        return self._hold(pair, "no_ict_setup")

    async def on_start(self) -> None:
        self._setup = None
        self._cooldown_remaining = 0

    async def on_stop(self) -> None:
        self._setup = None

    def _advance_setup(
        self,
        candle: dict,
        all_candles: list[dict],
        context: TradingContext,
    ) -> Optional[TradeSignal]:
        setup = self._setup
        if setup is None:
            return None

        if setup.state == "swept":
            setup.bars_since_sweep += 1
            if setup.bars_since_sweep > self._mss_max_bars:
                self._setup = None
                return self._hold(context.pair, "ict_setup_expired_before_mss")
            if self._is_mss(candle, setup):
                fvg = self._detect_fvg(all_candles, setup.direction)
                setup.state = "waiting_retest" if fvg is not None else "mss_confirmed"
                setup.bars_since_mss = 0
                if fvg is not None:
                    setup.fvg_low, setup.fvg_high = fvg
                    setup.bars_since_fvg = 0
                    return self._hold(context.pair, self._reason(setup, "mss_and_fvg_confirmed"))
                return self._hold(context.pair, self._reason(setup, "mss_confirmed_waiting_fvg"))

        if setup.state == "mss_confirmed":
            setup.bars_since_mss += 1
            if setup.bars_since_mss > self._fvg_max_bars:
                self._setup = None
                return self._hold(context.pair, "ict_setup_expired_before_fvg")
            fvg = self._detect_fvg(all_candles, setup.direction)
            if fvg is not None:
                setup.fvg_low, setup.fvg_high = fvg
                setup.state = "waiting_retest"
                setup.bars_since_fvg = 0
                return self._hold(context.pair, self._reason(setup, "fvg_confirmed_waiting_retest"))

        if setup.state == "waiting_retest":
            setup.bars_since_fvg += 1
            if setup.bars_since_fvg > self._retest_max_bars:
                self._setup = None
                return self._hold(context.pair, "ict_setup_expired_before_retest")
            if setup.bars_since_fvg >= 1 and self._is_retest(candle, setup):
                blocked_reason = self._entry_filter_block_reason(candle, all_candles, setup)
                if blocked_reason is not None:
                    return self._hold(context.pair, f"ict_entry_filter_blocked {blocked_reason}")
                signal = self._entry_signal(candle, context, setup)
                if signal is not None:
                    self._setup = None
                    self._cooldown_remaining = self._cooldown_bars
                    return signal
                self._setup = None
                return self._hold(context.pair, "ict_setup_invalid_risk")

        return None

    def _detect_sweep(self, candle: dict, history: list[dict]) -> Optional[_Setup]:
        recent_sweep = history[-self._sweep_lookback :]
        recent_mss = history[-self._mss_lookback :]
        close = self._price(candle, "close")
        low = self._price(candle, "low")
        high = self._price(candle, "high")

        if self._direction_mode in ("both", "long"):
            sweep_level = min(self._price(c, "low") for c in recent_sweep)
            required_low = sweep_level * (1.0 - self._min_sweep_pct / 100.0)
            if low < required_low and close > sweep_level:
                return _Setup(
                    direction="bullish",
                    state="swept",
                    sweep_level=sweep_level,
                    sweep_extreme=low,
                    mss_level=max(self._price(c, "high") for c in recent_mss),
                )

        if self._direction_mode in ("both", "short"):
            sweep_level = max(self._price(c, "high") for c in recent_sweep)
            required_high = sweep_level * (1.0 + self._min_sweep_pct / 100.0)
            if high > required_high and close < sweep_level:
                return _Setup(
                    direction="bearish",
                    state="swept",
                    sweep_level=sweep_level,
                    sweep_extreme=high,
                    mss_level=min(self._price(c, "low") for c in recent_mss),
                )
        return None

    def _is_mss(self, candle: dict, setup: _Setup) -> bool:
        close = self._price(candle, "close")
        if self._body_pct(candle) < self._min_mss_body_pct:
            return False

        if setup.direction == "bullish":
            required_close = setup.mss_level * (1.0 + self._min_mss_displacement_pct / 100.0)
            return close > required_close

        required_close = setup.mss_level * (1.0 - self._min_mss_displacement_pct / 100.0)
        return close < required_close

    def _detect_fvg(self, candles: list[dict], direction: Direction) -> Optional[tuple[float, float]]:
        if len(candles) < 3:
            return None
        first = candles[-3]
        third = candles[-1]
        close = max(self._price(third, "close"), 1e-12)

        if direction == "bullish":
            low = self._price(first, "high")
            high = self._price(third, "low")
            if high > low and ((high - low) / close) * 100.0 >= self._min_fvg_pct:
                return low, high
            return None

        low = self._price(third, "high")
        high = self._price(first, "low")
        if high > low and ((high - low) / close) * 100.0 >= self._min_fvg_pct:
            return low, high
        return None

    def _is_retest(self, candle: dict, setup: _Setup) -> bool:
        if setup.fvg_low is None or setup.fvg_high is None:
            return False
        low = self._price(candle, "low")
        high = self._price(candle, "high")
        close = self._price(candle, "close")
        overlaps = low <= setup.fvg_high and high >= setup.fvg_low
        if setup.direction == "bullish":
            return overlaps and close >= setup.fvg_low
        return overlaps and close <= setup.fvg_high

    def _entry_filter_block_reason(
        self,
        candle: dict,
        candles: list[dict],
        setup: _Setup,
    ) -> Optional[str]:
        if self._session_filter_mode == "utc" and not self._is_in_session(candle):
            return (
                f"outside_session_utc hour={self._candle_hour_utc(candle)} "
                f"window={self._session_start_hour_utc}-{self._session_end_hour_utc}"
            )

        if self._trend_filter_mode == "ema":
            trend_reason = self._trend_filter_block_reason(candles, setup.direction)
            if trend_reason is not None:
                return trend_reason

        if self._atr_filter_enabled:
            atr_pct = self._atr_pct(candles)
            if atr_pct is None:
                return "insufficient_atr_history"
            if atr_pct < self._min_atr_pct:
                return f"atr_too_low atr_pct={atr_pct:.4f} min={self._min_atr_pct:.4f}"
            if atr_pct > self._max_atr_pct:
                return f"atr_too_high atr_pct={atr_pct:.4f} max={self._max_atr_pct:.4f}"

        if self._retest_confirmation == "directional_close":
            open_ = self._price(candle, "open")
            close = self._price(candle, "close")
            if setup.direction == "bullish" and close <= open_:
                return "retest_not_bullish_close"
            if setup.direction == "bearish" and close >= open_:
                return "retest_not_bearish_close"

        return None

    def _trend_filter_block_reason(self, candles: list[dict], direction: Direction) -> Optional[str]:
        if len(candles) < self._trend_lookback:
            return "insufficient_trend_history"

        closes = [self._price(c, "close") for c in candles[-self._trend_lookback :]]
        ema = self._ema(closes)
        close = closes[-1]
        if direction == "bullish" and close < ema:
            return f"below_ema_trend close={close:.6f} ema={ema:.6f}"
        if direction == "bearish" and close > ema:
            return f"above_ema_trend close={close:.6f} ema={ema:.6f}"

        if self._min_trend_slope_pct > 0:
            if len(candles) < self._trend_lookback + 1:
                return "insufficient_trend_slope_history"
            prev_closes = [self._price(c, "close") for c in candles[-self._trend_lookback - 1 : -1]]
            prev_ema = self._ema(prev_closes)
            slope_pct = ((ema - prev_ema) / max(prev_ema, 1e-12)) * 100.0
            if direction == "bullish" and slope_pct < self._min_trend_slope_pct:
                return f"trend_slope_too_low slope_pct={slope_pct:.4f}"
            if direction == "bearish" and slope_pct > -self._min_trend_slope_pct:
                return f"trend_slope_too_low slope_pct={slope_pct:.4f}"

        return None

    def _entry_signal(self, candle: dict, context: TradingContext, setup: _Setup) -> Optional[TradeSignal]:
        entry_ref = self._price(candle, "close")
        if setup.direction == "bullish":
            sl_price = setup.sweep_extreme * (1.0 - self._sl_buffer_pct / 100.0)
            risk = entry_ref - sl_price
            if risk <= 0:
                return None
            tp_price = entry_ref + risk * self._reward_risk
            signal = Signal.LONG
        else:
            sl_price = setup.sweep_extreme * (1.0 + self._sl_buffer_pct / 100.0)
            risk = sl_price - entry_ref
            if risk <= 0:
                return None
            tp_price = entry_ref - risk * self._reward_risk
            signal = Signal.SHORT

        return TradeSignal(
            signal=signal,
            pair=context.pair,
            leverage=context.leverage,
            size_pct=self._size_pct,
            reason=self._reason(
                setup,
                f"retest_entry entry_ref={entry_ref:.6f} sl={sl_price:.6f} tp={tp_price:.6f}",
            ),
            tp_price=tp_price,
            sl_price=sl_price,
        )

    @staticmethod
    def _price(candle: dict, key: str) -> float:
        try:
            return float(candle[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"candle must contain numeric {key!r}") from exc

    @staticmethod
    def _choice(value: object, key: str, allowed: set[str]) -> str:
        parsed = str(value).strip().lower()
        if parsed not in allowed:
            raise ValueError(f"{key} must be one of {sorted(allowed)}")
        return parsed

    @staticmethod
    def _positive_int(value: object, key: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError(f"{key} must be a positive integer")
        return parsed

    @staticmethod
    def _non_negative_int(value: object, key: str) -> int:
        parsed = int(value)
        if parsed < 0:
            raise ValueError(f"{key} must be non-negative")
        return parsed

    @staticmethod
    def _bounded_int(value: object, key: str, lo: int, hi: int) -> int:
        parsed = int(value)
        if not lo <= parsed <= hi:
            raise ValueError(f"{key} must be >= {lo} and <= {hi}")
        return parsed

    @staticmethod
    def _positive_float(value: object, key: str) -> float:
        parsed = float(value)
        if parsed <= 0:
            raise ValueError(f"{key} must be positive")
        return parsed

    @staticmethod
    def _non_negative_float(value: object, key: str) -> float:
        parsed = float(value)
        if parsed < 0:
            raise ValueError(f"{key} must be non-negative")
        return parsed

    @staticmethod
    def _bounded_float(value: object, key: str, lo: float, hi: float) -> float:
        parsed = float(value)
        if not lo < parsed <= hi:
            raise ValueError(f"{key} must be > {lo} and <= {hi}")
        return parsed

    @staticmethod
    def _body_pct(candle: dict) -> float:
        high = ICTLiquidityFVGStrategy._price(candle, "high")
        low = ICTLiquidityFVGStrategy._price(candle, "low")
        range_ = high - low
        if range_ <= 0:
            return 0.0
        open_ = ICTLiquidityFVGStrategy._price(candle, "open")
        close = ICTLiquidityFVGStrategy._price(candle, "close")
        return abs(close - open_) / range_ * 100.0

    @staticmethod
    def _ema(values: list[float]) -> float:
        if not values:
            raise ValueError("values must not be empty")
        alpha = 2.0 / (len(values) + 1.0)
        ema = values[0]
        for value in values[1:]:
            ema = (value * alpha) + (ema * (1.0 - alpha))
        return ema

    def _atr_pct(self, candles: list[dict]) -> Optional[float]:
        if len(candles) < self._atr_period + 1:
            return None
        window = candles[-self._atr_period - 1 :]
        true_ranges: list[float] = []
        for prev, current in zip(window, window[1:]):
            high = self._price(current, "high")
            low = self._price(current, "low")
            prev_close = self._price(prev, "close")
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        close = max(self._price(window[-1], "close"), 1e-12)
        return (sum(true_ranges) / len(true_ranges)) / close * 100.0

    def _is_in_session(self, candle: dict) -> bool:
        hour = self._candle_hour_utc(candle)
        start = self._session_start_hour_utc
        end = self._session_end_hour_utc
        if start == end:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    @staticmethod
    def _candle_hour_utc(candle: dict) -> int:
        timestamp = candle.get("timestamp")
        if isinstance(timestamp, datetime):
            return timestamp.hour
        if isinstance(timestamp, str):
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return parsed.hour
        raise ValueError("candle must contain datetime or ISO string timestamp")

    @staticmethod
    def _hold(pair: str, reason: str) -> TradeSignal:
        return TradeSignal(signal=Signal.HOLD, pair=pair, reason=reason)

    def _reason(self, setup: _Setup, prefix: str) -> str:
        fvg = "none"
        if setup.fvg_low is not None and setup.fvg_high is not None:
            fvg = f"[{setup.fvg_low:.6f},{setup.fvg_high:.6f}]"
        return (
            f"ict_{setup.direction}_{prefix} "
            f"sweep_level={setup.sweep_level:.6f} sweep_extreme={setup.sweep_extreme:.6f} "
            f"mss_level={setup.mss_level:.6f} fvg={fvg} rr={self._reward_risk:.2f}"
        )
