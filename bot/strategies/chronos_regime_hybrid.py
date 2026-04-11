import asyncio

from app.config import settings
from app.core.regime_detector import MarketRegimeDetector
from app.core.strategy_base import BaseStrategy, Signal, TradeSignal, TradingContext
from app.logging_config import get_logger
from app.ml.chronos_service import get_chronos_service
from strategies.rsi_bollinger_regime import RSIBollingerRegimeStrategy

logger = get_logger(__name__)


class ChronosRegimeHybridStrategy(BaseStrategy):
    """Chronos-2 forecast + regime filter with RSI/BB fallback.

    Core idea:
      - Forecast near-future quantiles (q10/q50/q90) using Chronos-2.
      - Convert median forecast edge into directional entry/exit signals.
      - Use regime filter (trending_up / trending_down) to block counter-trend entries.
      - If Chronos is unavailable, fallback to rsi_bollinger_regime strategy.
    """

    name = "chronos_regime_hybrid"

    def __init__(self) -> None:
        self._chronos_enabled: bool = settings.CHRONOS_ENABLED
        self._model_id: str = settings.CHRONOS_MODEL_ID
        self._device_map: str = settings.CHRONOS_DEVICE_MAP
        self._chronos_timeout_sec: float = settings.CHRONOS_TIMEOUT_SEC
        self._prediction_length: int = settings.CHRONOS_PREDICTION_LENGTH
        self._min_context: int = settings.CHRONOS_MIN_CONTEXT

        self._entry_edge_pct: float = settings.CHRONOS_ENTRY_EDGE_PCT
        self._exit_edge_pct: float = settings.CHRONOS_EXIT_EDGE_PCT
        self._max_uncertainty_pct: float = settings.CHRONOS_MAX_UNCERTAINTY_PCT

        self._base_size_pct: float = settings.CHRONOS_BASE_SIZE_PCT
        self._min_size_pct: float = settings.CHRONOS_MIN_SIZE_PCT
        self._regime_confidence_min: float = settings.CHRONOS_REGIME_CONFIDENCE_MIN

        self._fallback_enabled: bool = True
        self._fallback = RSIBollingerRegimeStrategy()

        self._regime_detector = MarketRegimeDetector()

    @property
    def lookback_period(self) -> int:
        return max(self._min_context, self._fallback.lookback_period, 80)

    def configure(self, params: dict) -> None:
        if "chronos_enabled" in params:
            self._chronos_enabled = bool(params["chronos_enabled"])
        if "model_id" in params:
            self._model_id = str(params["model_id"]).strip() or self._model_id
        if "device_map" in params:
            self._device_map = str(params["device_map"]).strip() or self._device_map
        if "prediction_length" in params:
            self._prediction_length = max(1, int(params["prediction_length"]))
        if "chronos_timeout_sec" in params:
            self._chronos_timeout_sec = max(1.0, float(params["chronos_timeout_sec"]))
        if "min_context" in params:
            self._min_context = max(64, int(params["min_context"]))
        if "entry_edge_pct" in params:
            self._entry_edge_pct = max(0.01, float(params["entry_edge_pct"]))
        if "exit_edge_pct" in params:
            self._exit_edge_pct = max(0.0, float(params["exit_edge_pct"]))
        if "max_uncertainty_pct" in params:
            self._max_uncertainty_pct = max(0.01, float(params["max_uncertainty_pct"]))
        if "base_size_pct" in params:
            self._base_size_pct = max(1.0, min(100.0, float(params["base_size_pct"])))
        if "min_size_pct" in params:
            self._min_size_pct = max(1.0, min(100.0, float(params["min_size_pct"])))
        if "regime_confidence_min" in params:
            self._regime_confidence_min = max(0.0, min(1.0, float(params["regime_confidence_min"])))
        if "fallback_enabled" in params:
            self._fallback_enabled = bool(params["fallback_enabled"])
        if "fallback_params" in params and isinstance(params["fallback_params"], dict):
            self._fallback.configure(params["fallback_params"])

        logger.info(
            "chronos_regime_hybrid_configured",
            chronos_enabled=self._chronos_enabled,
            model_id=self._model_id,
            device_map=self._device_map,
            chronos_timeout_sec=self._chronos_timeout_sec,
            prediction_length=self._prediction_length,
            min_context=self._min_context,
            entry_edge_pct=self._entry_edge_pct,
            exit_edge_pct=self._exit_edge_pct,
            max_uncertainty_pct=self._max_uncertainty_pct,
            base_size_pct=self._base_size_pct,
            min_size_pct=self._min_size_pct,
            regime_confidence_min=self._regime_confidence_min,
            fallback_enabled=self._fallback_enabled,
        )

    @staticmethod
    def _normalize_direction(direction: str | None) -> str:
        value = (direction or "").strip().lower()
        if value in ("buy", "long"):
            return "long"
        if value in ("sell", "short"):
            return "short"
        return value or "unknown"

    @staticmethod
    def _infer_timeframe(candle: dict, history: list[dict]) -> str:
        if not history:
            return "1m"
        try:
            current_ts = int(str(candle.get("timestamp", "0")))
            prev_ts = int(str(history[-1].get("timestamp", "0")))
            delta_sec = abs(current_ts - prev_ts) // 1000
            if delta_sec <= 0:
                return "1m"
            if delta_sec % 86400 == 0:
                return f"{max(1, delta_sec // 86400)}D"
            if delta_sec % 3600 == 0:
                return f"{max(1, delta_sec // 3600)}H"
            return f"{max(1, delta_sec // 60)}m"
        except Exception:
            return "1m"

    def _build_fallback_signal(self, signal: TradeSignal, reason_prefix: str) -> TradeSignal:
        return TradeSignal(
            signal=signal.signal,
            pair=signal.pair,
            leverage=signal.leverage,
            size_pct=signal.size_pct,
            reason=f"{reason_prefix} | {signal.reason}",
            tp_price=signal.tp_price,
            sl_price=signal.sl_price,
            trailing_stop_pct=signal.trailing_stop_pct,
        )

    def _size_pct(self, edge_pct: float, uncertainty_pct: float) -> float:
        edge_strength = min(abs(edge_pct) / max(self._entry_edge_pct, 1e-9), 2.0)
        uncertainty_factor = max(
            0.0,
            1.0 - (uncertainty_pct / max(self._max_uncertainty_pct, 1e-9)),
        )
        raw = self._base_size_pct * edge_strength * uncertainty_factor
        return max(self._min_size_pct, min(100.0, raw))

    async def on_candle(
        self,
        candle: dict,
        history: list[dict],
        context: TradingContext,
    ) -> TradeSignal:
        all_candles = history + [candle]
        if len(all_candles) < self.lookback_period:
            return TradeSignal(signal=Signal.HOLD, pair=context.pair, reason="insufficient_history")

        closes = [float(c["close"]) for c in all_candles]
        highs = [float(c["high"]) for c in all_candles]
        lows = [float(c["low"]) for c in all_candles]
        volumes = [float(c.get("volume", 0.0)) for c in all_candles]
        price = closes[-1]

        regime = self._regime_detector.detect(
            closes=closes[-max(120, self.lookback_period) :],
            volumes=volumes[-max(120, self.lookback_period) :],
            highs=highs[-max(120, self.lookback_period) :],
            lows=lows[-max(120, self.lookback_period) :],
        )

        timeframe = self._infer_timeframe(candle, history)
        service = get_chronos_service(
            model_id=self._model_id,
            device_map=self._device_map,
            enabled=self._chronos_enabled,
            min_context=self._min_context,
        )
        try:
            forecast = await asyncio.wait_for(
                asyncio.to_thread(
                    service.forecast_quantiles,
                    closes,
                    prediction_length=self._prediction_length,
                    timeframe=timeframe,
                ),
                timeout=self._chronos_timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "chronos_inference_timeout",
                pair=context.pair,
                timeout_sec=self._chronos_timeout_sec,
            )
            forecast = None

        if forecast is None:
            if self._fallback_enabled:
                fallback_signal = await self._fallback.on_candle(candle, history, context)
                return self._build_fallback_signal(
                    fallback_signal,
                    "chronos_unavailable_fallback=rsi_bollinger_regime",
                )
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason="chronos_unavailable_no_fallback",
            )

        q10 = float(forecast.q10[-1])
        q50 = float(forecast.q50[-1])
        q90 = float(forecast.q90[-1])

        edge_pct = ((q50 - price) / max(price, 1e-9)) * 100.0
        uncertainty_pct = ((q90 - q10) / max(price, 1e-9)) * 100.0

        position = context.current_position
        direction = self._normalize_direction(position.get("direction")) if position else "flat"
        is_long = direction == "long"
        is_short = direction == "short"

        is_uptrend = (
            regime.regime == "trending_up"
            and regime.confidence >= self._regime_confidence_min
        )
        is_downtrend = (
            regime.regime == "trending_down"
            and regime.confidence >= self._regime_confidence_min
        )

        if uncertainty_pct > self._max_uncertainty_pct:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=(
                    f"high_uncertainty edge={edge_pct:.3f}% uncertainty={uncertainty_pct:.3f}% "
                    f"regime={regime.regime} conf={regime.confidence:.2f}"
                ),
            )

        long_cond = edge_pct >= self._entry_edge_pct
        short_cond = edge_pct <= -self._entry_edge_pct

        if position is not None:
            if is_long and (edge_pct <= self._exit_edge_pct or is_downtrend):
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=(
                        f"close_long edge={edge_pct:.3f}% regime={regime.regime} conf={regime.confidence:.2f}"
                    ),
                )
            if is_short and (edge_pct >= -self._exit_edge_pct or is_uptrend):
                return TradeSignal(
                    signal=Signal.CLOSE,
                    pair=context.pair,
                    reason=(
                        f"close_short edge={edge_pct:.3f}% regime={regime.regime} conf={regime.confidence:.2f}"
                    ),
                )

        if long_cond and is_downtrend:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=(
                    f"blocked_by_regime downtrend edge={edge_pct:.3f}% "
                    f"regime_conf={regime.confidence:.2f}"
                ),
            )
        if short_cond and is_uptrend:
            return TradeSignal(
                signal=Signal.HOLD,
                pair=context.pair,
                reason=(
                    f"blocked_by_regime uptrend edge={edge_pct:.3f}% "
                    f"regime_conf={regime.confidence:.2f}"
                ),
            )

        size_pct = self._size_pct(edge_pct=edge_pct, uncertainty_pct=uncertainty_pct)

        logger.debug(
            "chronos_regime_hybrid_signal_metrics",
            pair=context.pair,
            price=round(price, 4),
            q10=round(q10, 4),
            q50=round(q50, 4),
            q90=round(q90, 4),
            edge_pct=round(edge_pct, 4),
            uncertainty_pct=round(uncertainty_pct, 4),
            regime=regime.regime,
            regime_conf=round(regime.confidence, 4),
            timeframe=timeframe,
            size_pct=round(size_pct, 2),
        )

        if long_cond and not is_long:
            return TradeSignal(
                signal=Signal.LONG,
                pair=context.pair,
                leverage=context.leverage,
                size_pct=size_pct,
                reason=(
                    f"chronos_long edge={edge_pct:.3f}% uncertainty={uncertainty_pct:.3f}% "
                    f"regime={regime.regime} conf={regime.confidence:.2f}"
                ),
            )
        if short_cond and not is_short:
            return TradeSignal(
                signal=Signal.SHORT,
                pair=context.pair,
                leverage=context.leverage,
                size_pct=size_pct,
                reason=(
                    f"chronos_short edge={edge_pct:.3f}% uncertainty={uncertainty_pct:.3f}% "
                    f"regime={regime.regime} conf={regime.confidence:.2f}"
                ),
            )

        return TradeSignal(
            signal=Signal.HOLD,
            pair=context.pair,
            reason=(
                f"chronos_hold edge={edge_pct:.3f}% uncertainty={uncertainty_pct:.3f}% "
                f"regime={regime.regime} conf={regime.confidence:.2f}"
            ),
        )
