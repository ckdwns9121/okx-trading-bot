import numpy as np

from app.core.indicators import compute_atr
from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger

logger = get_logger(__name__)


class RSIBollingerRegimeStrategy(BaseStrategy):
    """RSI + Bollinger combo with regime filter.

    Base entry logic (same as rsi_bollinger_combo):
      - LONG  when RSI < oversold AND price < lower Bollinger Band
      - SHORT when RSI > overbought AND price > upper Bollinger Band
      - CLOSE when RSI returns to neutral zone (45-55)

    Regime filter (new):
      - Compute ADX + EMA trend alignment.
      - If strong uptrend, block SHORT entries.
      - If strong downtrend, block LONG entries.
      - In ranging regime, allow both directions.

    Goal: reduce counter-trend entries in persistent trend markets.
    """

    name = "rsi_bollinger_regime"

    def __init__(self) -> None:
        # RSI + BB params (original core)
        self._rsi_period: int = 14
        self._rsi_oversold: float = 35.0
        self._rsi_overbought: float = 65.0
        self._bb_period: int = 20
        self._bb_std: float = 2.0

        # Regime filter params (new)
        self._adx_period: int = 14
        self._adx_threshold: float = 25.0
        self._ema_fast_period: int = 21
        self._ema_slow_period: int = 55

        # Optional risk overlay. Defaults intentionally preserve the original
        # all-in signal behavior for existing backtests.
        self._size_pct: float = 100.0
        self._atr_period: int = 14
        self._tp_atr_mult: float | None = None
        self._sl_atr_mult: float | None = None
        self._trailing_stop_pct: float | None = None

    @property
    def lookback_period(self) -> int:
        # ADX typically needs ~2 * period bars for stable value.
        return max(
            self._rsi_period + 1,
            self._bb_period,
            self._ema_slow_period,
            self._adx_period * 2 + 1,
            self._atr_period + 1,
        )

    def configure(self, params: dict) -> None:
        """Optional overrides for all thresholds and periods."""
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

        if "adx_period" in params:
            period = int(params["adx_period"])
            if period <= 0:
                raise ValueError("adx_period must be a positive integer")
            self._adx_period = period
        if "adx_threshold" in params:
            self._adx_threshold = float(params["adx_threshold"])
        if "ema_fast_period" in params:
            period = int(params["ema_fast_period"])
            if period <= 0:
                raise ValueError("ema_fast_period must be a positive integer")
            self._ema_fast_period = period
        if "ema_slow_period" in params:
            period = int(params["ema_slow_period"])
            if period <= 0:
                raise ValueError("ema_slow_period must be a positive integer")
            self._ema_slow_period = period

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

        if self._ema_fast_period >= self._ema_slow_period:
            raise ValueError("ema_fast_period must be strictly less than ema_slow_period")
        if not 0.0 < self._size_pct <= 100.0:
            raise ValueError("size_pct must be in the range (0, 100]")

        logger.info(
            "rsi_bollinger_regime_configured",
            rsi_period=self._rsi_period,
            rsi_oversold=self._rsi_oversold,
            rsi_overbought=self._rsi_overbought,
            bb_period=self._bb_period,
            bb_std=self._bb_std,
            adx_period=self._adx_period,
            adx_threshold=self._adx_threshold,
            ema_fast_period=self._ema_fast_period,
            ema_slow_period=self._ema_slow_period,
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

    # ------------------------------------------------------------------ #
    # Indicator calculations                                               #
    # ------------------------------------------------------------------ #

    def _compute_rsi(self, closes: np.ndarray) -> float:
        if len(closes) < self._rsi_period + 1:
            return 50.0

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[: self._rsi_period]))
        avg_loss = float(np.mean(losses[: self._rsi_period]))

        for gain, loss in zip(gains[self._rsi_period :], losses[self._rsi_period :]):
            avg_gain = (avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
            avg_loss = (avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

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

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> float:
        alpha = 2.0 / (period + 1)
        ema = float(values[0])
        for v in values[1:]:
            ema = alpha * float(v) + (1.0 - alpha) * ema
        return ema

    def _compute_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        period = self._adx_period
        if len(closes) < period * 2 + 1:
            return 0.0

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
        )

        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        atr = float(np.mean(tr[:period]))
        plus_sm = float(np.mean(plus_dm[:period]))
        minus_sm = float(np.mean(minus_dm[:period]))

        dx_values: list[float] = []
        for i in range(period, len(tr)):
            atr = ((atr * (period - 1)) + float(tr[i])) / period
            plus_sm = ((plus_sm * (period - 1)) + float(plus_dm[i])) / period
            minus_sm = ((minus_sm * (period - 1)) + float(minus_dm[i])) / period

            if atr <= 0.0:
                dx_values.append(0.0)
                continue

            plus_di = 100.0 * (plus_sm / atr)
            minus_di = 100.0 * (minus_sm / atr)
            denom = plus_di + minus_di
            dx = 0.0 if denom <= 0.0 else 100.0 * abs(plus_di - minus_di) / denom
            dx_values.append(dx)

        if len(dx_values) < period:
            return 0.0

        adx = float(np.mean(dx_values[:period]))
        for dx in dx_values[period:]:
            adx = ((adx * (period - 1)) + dx) / period

        return adx

    def _classify_regime(self, closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> tuple[str, float, float, float]:
        adx = self._compute_adx(highs, lows, closes)
        ema_fast = self._ema(closes[-self._ema_fast_period :], self._ema_fast_period)
        ema_slow = self._ema(closes[-self._ema_slow_period :], self._ema_slow_period)

        if adx >= self._adx_threshold and ema_fast > ema_slow:
            return "uptrend", adx, ema_fast, ema_slow
        if adx >= self._adx_threshold and ema_fast < ema_slow:
            return "downtrend", adx, ema_fast, ema_slow
        return "ranging", adx, ema_fast, ema_slow

    def _risk_prices(
        self,
        signal: Signal,
        entry_price: float,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> tuple[float | None, float | None]:
        atr = compute_atr(highs, lows, closes, self._atr_period)
        if atr <= 0.0:
            return None, None

        tp_price = None
        sl_price = None
        if signal == Signal.LONG:
            if self._tp_atr_mult is not None:
                tp_price = entry_price + atr * self._tp_atr_mult
            if self._sl_atr_mult is not None:
                sl_price = entry_price - atr * self._sl_atr_mult
        elif signal == Signal.SHORT:
            if self._tp_atr_mult is not None:
                tp_price = entry_price - atr * self._tp_atr_mult
            if self._sl_atr_mult is not None:
                sl_price = entry_price + atr * self._sl_atr_mult

        return tp_price, sl_price

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

        rsi = self._compute_rsi(closes)
        bb_upper, bb_middle, bb_lower = self._compute_bollinger_bands(closes)
        price = float(candle["close"])
        regime, adx, ema_fast, ema_slow = self._classify_regime(closes, highs, lows)

        logger.debug(
            "rsi_bollinger_regime_indicators",
            pair=context.pair,
            rsi=round(rsi, 2),
            bb_upper=round(bb_upper, 4),
            bb_middle=round(bb_middle, 4),
            bb_lower=round(bb_lower, 4),
            price=round(price, 4),
            regime=regime,
            adx=round(adx, 2),
            ema_fast=round(ema_fast, 4),
            ema_slow=round(ema_slow, 4),
        )

        position = context.current_position
        is_long = position is not None and position.get("direction") in ("buy", "long")
        is_short = position is not None and position.get("direction") in ("sell", "short")

        if position is not None:
            if 45.0 <= rsi <= 55.0:
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"rsi_neutral_zone rsi={rsi:.2f}",
                )
            if is_long and regime == "downtrend":
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"regime_flip_to_downtrend adx={adx:.2f}",
                )
            if is_short and regime == "uptrend":
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=f"regime_flip_to_uptrend adx={adx:.2f}",
                )

        long_condition = rsi < self._rsi_oversold and price < bb_lower
        short_condition = rsi > self._rsi_overbought and price > bb_upper

        if long_condition and regime == "downtrend":
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=(
                    f"blocked_by_regime downtrend adx={adx:.2f} "
                    f"rsi={rsi:.2f} price={price:.4f} bb_lower={bb_lower:.4f}"
                ),
            )
        if short_condition and regime == "uptrend":
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=(
                    f"blocked_by_regime uptrend adx={adx:.2f} "
                    f"rsi={rsi:.2f} price={price:.4f} bb_upper={bb_upper:.4f}"
                ),
            )

        if long_condition and not is_long:
            tp_price, sl_price = self._risk_prices(Signal.LONG, price, highs, lows, closes)
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                size_pct=self._size_pct,
                reason=(
                    f"rsi_oversold+below_lower_band regime={regime} "
                    f"rsi={rsi:.2f} price={price:.4f} bb_lower={bb_lower:.4f} adx={adx:.2f}"
                ),
                tp_price=tp_price,
                sl_price=sl_price,
                trailing_stop_pct=self._trailing_stop_pct,
            )
        if short_condition and not is_short:
            tp_price, sl_price = self._risk_prices(Signal.SHORT, price, highs, lows, closes)
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                size_pct=self._size_pct,
                reason=(
                    f"rsi_overbought+above_upper_band regime={regime} "
                    f"rsi={rsi:.2f} price={price:.4f} bb_upper={bb_upper:.4f} adx={adx:.2f}"
                ),
                tp_price=tp_price,
                sl_price=sl_price,
                trailing_stop_pct=self._trailing_stop_pct,
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"regime={regime} adx={adx:.2f} rsi={rsi:.2f} "
                f"price={price:.4f} bb=[{bb_lower:.4f},{bb_upper:.4f}]"
            ),
        )
