"""Chronos-2 forecast service with lazy model loading and robust fallbacks."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from app.logging_config import get_logger

logger = get_logger(__name__)

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional dependency
    pd = None

try:
    from chronos import Chronos2Pipeline
except Exception:  # pragma: no cover - optional dependency
    Chronos2Pipeline = None


@dataclass
class ChronosQuantileForecast:
    q10: list[float]
    q50: list[float]
    q90: list[float]


class ChronosForecastService:
    """Thread-safe singleton-like service for Chronos-2 inference."""

    def __init__(
        self,
        *,
        model_id: str,
        device_map: str = "cpu",
        enabled: bool = False,
        min_context: int = 256,
    ) -> None:
        self._model_id = model_id
        self._device_map = device_map
        self._enabled = enabled
        self._min_context = max(32, min_context)

        self._pipeline = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._infer_lock_timeout_sec = 2.0

        self._dep_warned = False
        self._load_error: str | None = None
        self._load_failures = 0
        self._retry_after: datetime | None = None
        self._base_retry_seconds = 30
        self._max_retry_seconds = 15 * 60

        self._last_key: tuple | None = None
        self._last_result: ChronosQuantileForecast | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _warn_missing_dependency_once(self) -> None:
        if self._dep_warned:
            return
        self._dep_warned = True
        logger.warning(
            "chronos_dependencies_missing",
            message=(
                "Chronos dependencies are unavailable. Install with "
                "`pip install \".[ml]\"` (in repo) or "
                "`pip install \"chronos-forecasting>=2.0\" \"pandas[pyarrow]\"` "
                "or disable CHRONOS_ENABLED."
            ),
        )

    def _ensure_pipeline(self):
        if not self._enabled:
            return None

        if Chronos2Pipeline is None or pd is None:
            self._warn_missing_dependency_once()
            return None

        now = datetime.now(timezone.utc)
        if self._retry_after is not None and now < self._retry_after:
            return None

        if self._pipeline is not None:
            return self._pipeline

        load_lock_acquired = self._load_lock.acquire(blocking=False)
        if not load_lock_acquired:
            logger.debug("chronos_pipeline_load_in_progress")
            return None

        try:
            now = datetime.now(timezone.utc)
            if self._retry_after is not None and now < self._retry_after:
                return None
            if self._pipeline is not None:
                return self._pipeline
            try:
                logger.info(
                    "chronos_pipeline_loading",
                    model_id=self._model_id,
                    device_map=self._device_map,
                )
                self._pipeline = Chronos2Pipeline.from_pretrained(
                    self._model_id,
                    device_map=self._device_map,
                )
                self._load_failures = 0
                self._retry_after = None
                logger.info("chronos_pipeline_loaded", model_id=self._model_id)
            except Exception as exc:
                self._load_error = str(exc)
                self._load_failures += 1
                cooldown = min(
                    self._max_retry_seconds,
                    self._base_retry_seconds * (2 ** max(0, self._load_failures - 1)),
                )
                self._retry_after = datetime.now(timezone.utc) + timedelta(seconds=cooldown)
                logger.error(
                    "chronos_pipeline_load_failed",
                    model_id=self._model_id,
                    error=self._load_error,
                    retry_after=self._retry_after.isoformat() if self._retry_after else None,
                )
                return None
        finally:
            self._load_lock.release()

        return self._pipeline

    @staticmethod
    def _timeframe_to_timedelta(timeframe: str | None) -> timedelta:
        if not timeframe:
            return timedelta(minutes=1)
        tf = timeframe.strip()
        try:
            if not tf:
                return timedelta(minutes=1)

            unit = tf[-1]
            value = max(1, int(tf[:-1]))

            # Keep "m" (minutes) and "M" (months) distinct by case.
            if unit == "m":
                return timedelta(minutes=value)
            if unit in ("h", "H"):
                return timedelta(hours=value)
            if unit in ("d", "D"):
                return timedelta(days=value)
            if unit in ("w", "W"):
                return timedelta(weeks=value)
            if unit == "M":
                return timedelta(days=30 * value)
        except Exception:
            pass
        return timedelta(minutes=1)

    @staticmethod
    def _pick_quantile_column(frame, quantile: float):
        target_str = f"{quantile:.1f}"
        target_alt = f"{quantile:.2f}"
        candidates = {
            target_str,
            target_alt,
            f"q{target_str}",
            f"q{target_alt}",
            f"quantile_{target_str}",
            f"quantile_{target_alt}",
        }
        for col in frame.columns:
            col_str = str(col)
            if col_str in candidates:
                return col
            try:
                if abs(float(col_str) - quantile) < 1e-6:
                    return col
            except Exception:
                continue
        return None

    def _predict_df(
        self,
        pipeline,
        df,
        prediction_length: int,
        quantiles: tuple[float, float, float],
    ):
        kwargs = {
            "prediction_length": prediction_length,
            "id_column": "item_id",
            "timestamp_column": "timestamp",
            "quantile_levels": list(quantiles),
        }
        for target_key in ("target_column", "target"):
            try:
                return pipeline.predict_df(df=df, **kwargs, **{target_key: "target"})
            except TypeError:
                continue

        # Final fallback: old signature
        return pipeline.predict_df(
            df,
            prediction_length=prediction_length,
            id_column="item_id",
            timestamp_column="timestamp",
            target="target",
            quantile_levels=list(quantiles),
        )

    def forecast_quantiles(
        self,
        closes: Sequence[float],
        *,
        prediction_length: int,
        timeframe: str | None = None,
    ) -> ChronosQuantileForecast | None:
        if not self._enabled:
            return None
        if len(closes) < self._min_context:
            return None

        pipeline = self._ensure_pipeline()
        if pipeline is None or pd is None:
            return None

        quantiles = (0.1, 0.5, 0.9)
        context = [float(x) for x in closes[-self._min_context :]]
        cache_tail = tuple(round(x, 6) for x in context[-16:])
        cache_key = (cache_tail, len(context), prediction_length, timeframe)
        if cache_key == self._last_key and self._last_result is not None:
            return self._last_result

        delta = self._timeframe_to_timedelta(timeframe)
        start_ts = datetime.now(timezone.utc) - delta * (len(context) - 1)
        timestamps = [start_ts + i * delta for i in range(len(context))]

        df = pd.DataFrame(
            {
                "item_id": ["asset-1"] * len(context),
                "timestamp": timestamps,
                "target": context,
            }
        )

        # Serialize concurrent inference requests, but cap wait time to avoid
        # thread buildup when callers timeout/cancel upstream.
        lock_acquired = self._infer_lock.acquire(timeout=self._infer_lock_timeout_sec)
        if not lock_acquired:
            logger.debug(
                "chronos_inference_busy_timeout",
                timeout_sec=self._infer_lock_timeout_sec,
            )
            # Prefer last known model output over hard fallback when contention is high.
            if self._last_result is not None:
                return self._last_result
            return None

        try:
            pred = self._predict_df(
                pipeline,
                df=df,
                prediction_length=prediction_length,
                quantiles=quantiles,
            )
        except Exception as exc:
            logger.warning("chronos_predict_failed", error=str(exc))
            return None
        finally:
            self._infer_lock.release()

        if pred is None or len(pred) == 0:
            return None

        pred_item = pred
        if "item_id" in pred.columns:
            pred_item = pred[pred["item_id"] == "asset-1"]
            if len(pred_item) == 0:
                pred_item = pred

        q10_col = self._pick_quantile_column(pred_item, 0.1)
        q50_col = self._pick_quantile_column(pred_item, 0.5)
        q90_col = self._pick_quantile_column(pred_item, 0.9)
        if q10_col is None or q50_col is None or q90_col is None:
            logger.warning(
                "chronos_quantile_columns_missing",
                columns=[str(c) for c in pred_item.columns],
            )
            return None

        try:
            result = ChronosQuantileForecast(
                q10=[float(v) for v in pred_item[q10_col].tail(prediction_length).tolist()],
                q50=[float(v) for v in pred_item[q50_col].tail(prediction_length).tolist()],
                q90=[float(v) for v in pred_item[q90_col].tail(prediction_length).tolist()],
            )
        except Exception as exc:
            logger.warning("chronos_quantile_parse_failed", error=str(exc))
            return None

        if not result.q50:
            return None

        self._last_key = cache_key
        self._last_result = result
        return result


_SERVICES: dict[tuple[str, str, bool, int], ChronosForecastService] = {}
_SERVICES_LOCK = threading.Lock()


def get_chronos_service(
    *,
    model_id: str,
    device_map: str,
    enabled: bool,
    min_context: int,
) -> ChronosForecastService:
    key = (model_id, device_map, enabled, min_context)
    with _SERVICES_LOCK:
        service = _SERVICES.get(key)
        if service is None:
            service = ChronosForecastService(
                model_id=model_id,
                device_map=device_map,
                enabled=enabled,
                min_context=min_context,
            )
            _SERVICES[key] = service
        return service
