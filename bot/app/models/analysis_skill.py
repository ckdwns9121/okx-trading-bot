"""Pydantic schemas for analysis-skill API request/response contracts.

This module intentionally keeps canonical metric keys as the internal contract
while providing boundary-friendly alias compatibility for request payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# Canonical metric contract used for scoring/storage/analytics.
CANONICAL_METRIC_KEYS = {
    "total_pnl",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "trade_count",
}

# API boundary aliases (input compatibility only).
METRIC_ALIAS_TO_CANONICAL = {
    "sharpe": "sharpe_ratio",
    "mdd": "max_drawdown",
}


class MetricAliasError(ValueError):
    """Raised when metric payloads contain invalid/ambiguous key combinations."""


def normalize_metric_keys(metrics: dict[str, Any], *, strict: bool = True) -> dict[str, float]:
    """Normalize alias keys to canonical metric names.

    - Converts `sharpe` -> `sharpe_ratio`
    - Converts `mdd` -> `max_drawdown`
    - Validates canonical keys and optional strictness for unknown keys.
    """

    normalized: dict[str, float] = {}
    for raw_key, raw_value in metrics.items():
        key = METRIC_ALIAS_TO_CANONICAL.get(raw_key, raw_key)
        if key not in CANONICAL_METRIC_KEYS:
            if strict:
                raise MetricAliasError(f"Unsupported metric key: {raw_key!r}")
            continue

        if key in normalized:
            raise MetricAliasError(
                f"Duplicate metric value for key {key!r} from inputs {raw_key!r} and "
                "canonical mapping"
            )

        try:
            normalized[key] = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise MetricAliasError(
                f"Metric value for key {raw_key!r} must be numeric"
            ) from exc

    return normalized


def canonical_metrics_for_response(**metrics: float) -> dict[str, float]:
    """Build canonical metric dict from keyword args or aliases.

    Example:
      canonical_metrics_for_response(sharpe=1.2, max_drawdown=0.03)
      -> {"sharpe_ratio": 1.2, "max_drawdown": 0.03, ...}
    """

    data = normalize_metric_keys(metrics)
    missing = CANONICAL_METRIC_KEYS - data.keys()
    if missing:
        raise MetricAliasError(f"Missing required canonical metrics: {sorted(missing)}")
    return data


class AnalysisWindow(BaseModel):
    name: Literal["train", "val", "holdout"] = Field(...)
    start: str = Field(...)
    end: str = Field(...)

    @field_validator("start", "end")
    @classmethod
    def _validate_datetime(cls, value: str) -> str:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 datetime: {value!r}") from exc
        if dt.tzinfo is not None:
            # normalize to naive UTC-like local string by dropping tzinfo for internal callers.
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()


class AnalysisAssumptions(BaseModel):
    initial_balance: float = Field(..., gt=0)
    leverage: int = Field(..., ge=1, le=125)
    fee_rate: float = Field(..., ge=0)
    slippage_pct: float = Field(..., ge=0)
    funding_rate_per_8h: float = Field(...)
    cooldown_candles: int = Field(..., ge=0)
    liquidity_impact_factor: float = Field(..., ge=0)
    maintenance_margin_ratio: float = Field(..., ge=0, le=1)
    liquidation_fee_pct: float = Field(..., ge=0)


class AnalysisRunLimits(BaseModel):
    max_combinations: int = Field(default=100, ge=1, le=500)
    timeout_sec: int = Field(default=900, ge=1, le=1800)
    retry_per_failed_job: int = Field(default=1, ge=0, le=2)
    partial_failure_threshold: float = Field(default=0.2, ge=0.0, le=1.0)


class AnalysisRequest(BaseModel):
    strategy_name: str = Field(...)
    baseline_strategy_name: str = Field(...)
    pair: str = Field(...)
    timeframe: str = Field(...)
    windows: list[AnalysisWindow]
    assumptions: AnalysisAssumptions
    search_space: dict[str, list[float] | tuple[float, float]]
    top_k: int = Field(default=3, ge=1, le=3)
    run_limits: AnalysisRunLimits = Field(default_factory=AnalysisRunLimits)

    @model_validator(mode="after")
    def _validate_windows(self) -> "AnalysisRequest":
        if len(self.windows) != 3:
            raise ValueError("windows must contain exactly 3 entries: train, val, holdout")

        names = [w.name for w in self.windows]
        if sorted(names) != ["holdout", "train", "val"]:
            raise ValueError("windows must include train, val, holdout exactly once each")

        start_by_name = {w.name: datetime.fromisoformat(w.start) for w in self.windows}
        end_by_name = {w.name: datetime.fromisoformat(w.end) for w in self.windows}
        for name in ("train", "val", "holdout"):
            if end_by_name[name] <= start_by_name[name]:
                raise ValueError(f"Window {name!r} requires end > start")
        return self

    @model_validator(mode="after")
    def _validate_search_space(self) -> "AnalysisRequest":
        if not self.search_space:
            raise ValueError("search_space must not be empty")

        normalized: dict[str, tuple[float, float]] = {}
        for key, raw_range in self.search_space.items():
            if not isinstance(raw_range, (list, tuple)) or len(raw_range) != 2:
                raise ValueError(f"search_space[{key!r}] must be a 2-length range")
            low, high = raw_range
            try:
                low_v = float(low)
                high_v = float(high)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"search_space[{key!r}] values must be numeric") from exc
            if low_v > high_v:
                raise ValueError(f"search_space[{key!r}] low must be <= high")
            normalized[key] = (low_v, high_v)

        object.__setattr__(self, "search_space", normalized)
        return self


class MetricsByWindow(BaseModel):
    train: dict[str, float]
    val: dict[str, float]
    holdout: dict[str, float]

    @model_validator(mode="after")
    def _normalize(self) -> "MetricsByWindow":
        self.train = self._normalize_window(self.train)
        self.val = self._normalize_window(self.val)
        self.holdout = self._normalize_window(self.holdout)
        return self

    @field_validator("train", "val", "holdout", mode="before")
    @classmethod
    def _normalize_window_fields(cls, value: dict[str, Any]) -> dict[str, float]:
        return cls._normalize_window(value)

    @staticmethod
    def _normalize_window(value: dict[str, Any]) -> dict[str, float]:
        normalized = normalize_metric_keys(value)
        missing = CANONICAL_METRIC_KEYS - normalized.keys()
        if missing:
            raise ValueError(f"missing required metric keys: {', '.join(sorted(missing))}")
        return normalized


class RunFailures(BaseModel):
    failed_combinations: int
    failure_ratio: float
    degraded_mode: bool


class BaselineResult(BaseModel):
    metrics_by_window: MetricsByWindow


class Recommendation(BaseModel):
    rank: int = Field(..., ge=1)
    params: dict[str, float]
    metrics_by_window: MetricsByWindow
    baseline_delta_by_window: MetricsByWindow
    replay_pass: bool
    replay_delta: dict[str, float]


class AnalysisResponse(BaseModel):
    run_id: str
    status: str
    recommendation_count: int
    recommendations: list[Recommendation]
    baseline: BaselineResult
    failures: RunFailures


__all__ = [
    "AnalysisRequest",
    "AnalysisResponse",
    "AnalysisWindow",
    "AnalysisAssumptions",
    "AnalysisRunLimits",
    "RunFailures",
    "Recommendation",
    "BaselineResult",
    "MetricsByWindow",
    "CANONICAL_METRIC_KEYS",
    "METRIC_ALIAS_TO_CANONICAL",
    "normalize_metric_keys",
    "canonical_metrics_for_response",
    "MetricAliasError",
]
