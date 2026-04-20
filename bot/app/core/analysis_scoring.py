"""Scoring utilities for analysis-skill windows and recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.analysis_skill import (
    CANONICAL_METRIC_KEYS,
    METRIC_ALIAS_TO_CANONICAL,
)


def _coerce_float(name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metric {name!r} must be numeric") from exc


def normalize_metrics(metrics: dict[str, Any], *, allow_alias: bool = True) -> dict[str, float]:
    """Normalize a per-window metric map into canonical metric keys.

    Accepts canonical keys plus boundary aliases (`sharpe`, `mdd`) by default.
    """
    normalized: dict[str, float] = {}
    for raw_key, raw_value in metrics.items():
        key = METRIC_ALIAS_TO_CANONICAL[raw_key] if allow_alias and raw_key in METRIC_ALIAS_TO_CANONICAL else raw_key
        if key not in CANONICAL_METRIC_KEYS:
            raise ValueError(f"unsupported metric key: {raw_key!r}")
        if key in normalized:
            raise ValueError(f"duplicate metric key for {key!r}")
        normalized[key] = _coerce_float(raw_key, raw_value)

    missing = CANONICAL_METRIC_KEYS - normalized.keys()
    if missing:
        raise ValueError(f"missing canonical metrics: {', '.join(sorted(missing))}")

    return normalized


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_window_metrics(metrics: dict[str, float]) -> float:
    """Compute normalized score for a single window.

    Formula follows the canonical validation pipeline style but bounded for
    stable ranking in analysis runs.
    """
    sharpe_ratio = _coerce_float("sharpe_ratio", metrics["sharpe_ratio"])
    max_drawdown = _coerce_float("max_drawdown", metrics["max_drawdown"])
    win_rate = _coerce_float("win_rate", metrics["win_rate"])

    norm_sharpe = _clamp(sharpe_ratio + 1.0, 0.0, 4.0) / 4.0
    norm_mdd = 1.0 - _clamp(max_drawdown, 0.0, 1.0)
    norm_wr = _clamp(win_rate, 0.0, 1.0)

    # Trade count is a robustness bonus capped at 100 for normalization.
    trade_count = _coerce_float("trade_count", metrics.get("trade_count", 0.0))
    norm_tc = _clamp(trade_count / 100.0, 0.0, 1.0)

    return round(norm_sharpe * 0.4 + norm_mdd * 0.35 + norm_wr * 0.25, 8)


def score_candidate(metrics_by_window: dict[str, dict[str, float]]) -> float:
    """Score a candidate using weighted train/val/holdout metrics."""
    required_windows = {"train", "val", "holdout"}
    missing_windows = required_windows - metrics_by_window.keys()
    if missing_windows:
        raise ValueError(f"missing windows: {', '.join(sorted(missing_windows))}")

    normalized_windows = {
        window: normalize_metrics(raw_metrics)
        for window, raw_metrics in metrics_by_window.items()
    }
    window_scores = {
        "train": score_window_metrics(normalized_windows["train"]),
        "val": score_window_metrics(normalized_windows["val"]),
        "holdout": score_window_metrics(normalized_windows["holdout"]),
    }

    # Weight holdout more heavily because it is closer to out-of-sample behavior.
    score = (
        window_scores["train"] * 0.2
        + window_scores["val"] * 0.3
        + window_scores["holdout"] * 0.5
    )
    return round(float(score), 10)


@dataclass(frozen=True)
class WindowedCandidateScore:
    score: float
    window_scores: dict[str, float]
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: float


def score_and_breakdown(metrics_by_window: dict[str, dict[str, float]]) -> WindowedCandidateScore:
    """Return both aggregate score and selected canonical window metrics."""
    normalized = {
        window: normalize_metrics(raw)
        for window, raw in metrics_by_window.items()
    }
    window_scores = {
        "train": score_window_metrics(normalized["train"]),
        "val": score_window_metrics(normalized["val"]),
        "holdout": score_window_metrics(normalized["holdout"]),
    }
    aggregate = round(
        window_scores["train"] * 0.2
        + window_scores["val"] * 0.3
        + window_scores["holdout"] * 0.5,
        10,
    )

    # Holdout is used as canonical candidate score for ranking tie-breakers.
    holdout = normalized["holdout"]
    return WindowedCandidateScore(
        score=aggregate,
        window_scores=window_scores,
        total_pnl=float(holdout["total_pnl"]),
        sharpe_ratio=float(holdout["sharpe_ratio"]),
        max_drawdown=float(holdout["max_drawdown"]),
        win_rate=float(holdout["win_rate"]),
        trade_count=float(holdout["trade_count"]),
    )


__all__ = [
    "normalize_metrics",
    "score_window_metrics",
    "score_candidate",
    "score_and_breakdown",
    "WindowedCandidateScore",
]
