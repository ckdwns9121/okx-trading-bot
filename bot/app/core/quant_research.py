"""Research-only quant helpers for walk-forward, survival, volatility, and stat-arb analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from app.core.indicators import compute_atr

CANONICAL_METRIC_KEYS = (
    "total_pnl",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "trade_count",
)


@dataclass(frozen=True)
class WalkForwardSummary:
    complete: bool
    status: str
    fold_count: int
    total_evaluation_pnl: float
    average_evaluation_sharpe: float
    worst_evaluation_drawdown: float
    average_evaluation_win_rate: float
    average_evaluation_trade_count: float
    failure_reason: str | None = None


@dataclass(frozen=True)
class VolatilityRegime:
    regime: str
    bb_width_pct: float
    atr_pct: float


def _normalize_metrics(metrics: Mapping[str, Any]) -> dict[str, float] | None:
    normalized: dict[str, float] = {}
    for key in CANONICAL_METRIC_KEYS:
        if key not in metrics:
            return None
        normalized[key] = float(metrics[key])
    return normalized


def _has_window_bounds(window: Mapping[str, Any] | None) -> bool:
    if not isinstance(window, Mapping):
        return False
    return "start" in window and "end" in window


def summarize_walk_forward_evaluation(
    folds: Sequence[Mapping[str, Any]],
    *,
    expected_folds: int | None = None,
) -> WalkForwardSummary:
    """Summarize fixed walk-forward folds and fail closed on incomplete inputs.

    Each fold must provide:
    - ``train_window`` and ``evaluation_window`` mappings with ``start`` / ``end``
    - ``train_params`` mapping
    - ``train_metrics`` and ``evaluation_metrics`` with canonical metric keys

    ``evaluation_params`` is optional; if present it must match ``train_params``.
    This helper rejects any evaluation-window retuning.
    """
    if not folds:
        return WalkForwardSummary(
            complete=False,
            status="incomplete_data",
            fold_count=0,
            total_evaluation_pnl=0.0,
            average_evaluation_sharpe=0.0,
            worst_evaluation_drawdown=0.0,
            average_evaluation_win_rate=0.0,
            average_evaluation_trade_count=0.0,
            failure_reason="no_folds",
        )

    if expected_folds is not None and len(folds) != expected_folds:
        return WalkForwardSummary(
            complete=False,
            status="incomplete_data",
            fold_count=len(folds),
            total_evaluation_pnl=0.0,
            average_evaluation_sharpe=0.0,
            worst_evaluation_drawdown=0.0,
            average_evaluation_win_rate=0.0,
            average_evaluation_trade_count=0.0,
            failure_reason="fold_count_mismatch",
        )

    evaluation_metrics: list[dict[str, float]] = []
    for fold in folds:
        if not _has_window_bounds(fold.get("train_window")) or not _has_window_bounds(fold.get("evaluation_window")):
            return WalkForwardSummary(
                complete=False,
                status="incomplete_data",
                fold_count=len(evaluation_metrics),
                total_evaluation_pnl=0.0,
                average_evaluation_sharpe=0.0,
                worst_evaluation_drawdown=0.0,
                average_evaluation_win_rate=0.0,
                average_evaluation_trade_count=0.0,
                failure_reason="missing_window_bounds",
            )

        train_params = fold.get("train_params")
        if not isinstance(train_params, Mapping):
            return WalkForwardSummary(
                complete=False,
                status="incomplete_data",
                fold_count=len(evaluation_metrics),
                total_evaluation_pnl=0.0,
                average_evaluation_sharpe=0.0,
                worst_evaluation_drawdown=0.0,
                average_evaluation_win_rate=0.0,
                average_evaluation_trade_count=0.0,
                failure_reason="missing_train_params",
            )

        train_metrics = _normalize_metrics(fold.get("train_metrics", {}))
        evaluation = _normalize_metrics(fold.get("evaluation_metrics", {}))
        if train_metrics is None or evaluation is None:
            return WalkForwardSummary(
                complete=False,
                status="incomplete_data",
                fold_count=len(evaluation_metrics),
                total_evaluation_pnl=0.0,
                average_evaluation_sharpe=0.0,
                worst_evaluation_drawdown=0.0,
                average_evaluation_win_rate=0.0,
                average_evaluation_trade_count=0.0,
                failure_reason="missing_metrics",
            )

        evaluation_params = fold.get("evaluation_params")
        if evaluation_params is not None and dict(evaluation_params) != dict(train_params):
            return WalkForwardSummary(
                complete=False,
                status="evaluation_window_retuned",
                fold_count=len(evaluation_metrics),
                total_evaluation_pnl=0.0,
                average_evaluation_sharpe=0.0,
                worst_evaluation_drawdown=0.0,
                average_evaluation_win_rate=0.0,
                average_evaluation_trade_count=0.0,
                failure_reason="evaluation_params_changed",
            )

        evaluation_metrics.append(evaluation)

    sharpe_values = [metrics["sharpe_ratio"] for metrics in evaluation_metrics]
    drawdowns = [metrics["max_drawdown"] for metrics in evaluation_metrics]
    win_rates = [metrics["win_rate"] for metrics in evaluation_metrics]
    trade_counts = [metrics["trade_count"] for metrics in evaluation_metrics]
    pnl_values = [metrics["total_pnl"] for metrics in evaluation_metrics]

    return WalkForwardSummary(
        complete=True,
        status="ok",
        fold_count=len(evaluation_metrics),
        total_evaluation_pnl=float(sum(pnl_values)),
        average_evaluation_sharpe=float(np.mean(sharpe_values)),
        worst_evaluation_drawdown=float(max(drawdowns)),
        average_evaluation_win_rate=float(np.mean(win_rates)),
        average_evaluation_trade_count=float(np.mean(trade_counts)),
    )


def survival_score(metrics: Mapping[str, Any], *, initial_balance: float | None = None) -> float:
    """Score a candidate using Monte Carlo survival-oriented fields."""
    starting_balance = float(initial_balance if initial_balance is not None else metrics.get("initial_balance", 0.0))
    if starting_balance <= 0.0:
        raise ValueError("initial_balance must be positive")

    p5_ratio = float(metrics["p5_final_balance"]) / starting_balance
    median_ratio = float(metrics["median_final_balance"]) / starting_balance
    ruin_safety = 1.0 - float(metrics["ruin_probability"])
    drawdown_safety = 1.0 - min(max(float(metrics["p95_max_drawdown"]), 0.0), 1.0)

    return (
        p5_ratio * 0.4
        + median_ratio * 0.2
        + ruin_safety * 0.25
        + drawdown_safety * 0.15
    )


def rank_candidates_by_survival(
    candidates: Sequence[Mapping[str, Any]],
    *,
    initial_balance: float | None = None,
) -> list[dict[str, Any]]:
    """Return candidates ranked by survival score using Monte Carlo fields."""
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        row["survival_score"] = survival_score(candidate, initial_balance=initial_balance)
        ranked.append(row)

    ranked.sort(key=lambda item: float(item["survival_score"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["survival_rank"] = index
    return ranked


def compute_bb_width_pct(bb_upper: float, bb_middle: float, bb_lower: float) -> float:
    if bb_middle == 0.0:
        return 0.0
    return ((bb_upper - bb_lower) / bb_middle) * 100.0


def compute_atr_pct(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    period: int = 14,
) -> float:
    latest_close = float(closes[-1]) if len(closes) > 0 else 0.0
    if latest_close == 0.0:
        return 0.0
    return compute_atr(highs, lows, closes, period=period) / latest_close * 100.0


def classify_volatility_regime(
    bb_width_pct: float,
    atr_pct: float,
    *,
    low_bb_width_pct: float = 2.0,
    high_bb_width_pct: float = 8.0,
    low_atr_pct: float = 1.0,
    high_atr_pct: float = 3.0,
) -> VolatilityRegime:
    """Classify low/normal/high volatility from Bollinger width and ATR percentages."""
    if bb_width_pct <= low_bb_width_pct or atr_pct <= low_atr_pct:
        regime = "low"
    elif bb_width_pct >= high_bb_width_pct or atr_pct >= high_atr_pct:
        regime = "high"
    else:
        regime = "normal"
    return VolatilityRegime(regime=regime, bb_width_pct=float(bb_width_pct), atr_pct=float(atr_pct))


def volatility_profile_matches(profile: str, regime: str) -> bool:
    if profile == "any":
        return True
    return profile == regime


def price_ratio(base_prices: Sequence[float], quote_prices: Sequence[float]) -> np.ndarray:
    base = np.asarray(base_prices, dtype=float)
    quote = np.asarray(quote_prices, dtype=float)
    if len(base) != len(quote):
        raise ValueError("price series must have equal length")
    if len(base) == 0:
        return np.array([], dtype=float)
    if np.any(quote == 0.0):
        raise ValueError("quote price series contains zero")
    return base / quote


def rolling_correlation_stability(
    series_a: Sequence[float],
    series_b: Sequence[float],
    *,
    window: int,
) -> dict[str, float]:
    """Measure how stable rolling correlation remains across a window."""
    left = np.asarray(series_a, dtype=float)
    right = np.asarray(series_b, dtype=float)
    if len(left) != len(right):
        raise ValueError("series must have equal length")
    if window < 2:
        raise ValueError("window must be at least 2")
    if len(left) < window:
        return {
            "mean_correlation": 0.0,
            "correlation_std": 0.0,
            "stability_score": 0.0,
            "sample_count": 0.0,
        }

    correlations: list[float] = []
    for start in range(0, len(left) - window + 1):
        corr = np.corrcoef(left[start : start + window], right[start : start + window])[0, 1]
        if np.isfinite(corr):
            correlations.append(float(corr))

    if not correlations:
        return {
            "mean_correlation": 0.0,
            "correlation_std": 0.0,
            "stability_score": 0.0,
            "sample_count": 0.0,
        }

    mean_corr = float(np.mean(correlations))
    corr_std = float(np.std(correlations))
    stability_score = max(0.0, abs(mean_corr)) * max(0.0, 1.0 - corr_std)
    return {
        "mean_correlation": mean_corr,
        "correlation_std": corr_std,
        "stability_score": stability_score,
        "sample_count": float(len(correlations)),
    }


def zscore_signal(
    spread: Sequence[float],
    *,
    window: int,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
) -> dict[str, float | str]:
    """Generate a simple z-score signal from the latest spread sample."""
    values = np.asarray(spread, dtype=float)
    if window < 2:
        raise ValueError("window must be at least 2")
    if len(values) < window:
        return {"zscore": 0.0, "signal": "hold"}

    trailing = values[-window:]
    mean = float(np.mean(trailing))
    std = float(np.std(trailing, ddof=0))
    if std == 0.0:
        return {"zscore": 0.0, "signal": "hold"}

    zscore = (float(values[-1]) - mean) / std
    if zscore >= entry_threshold:
        signal = "short_spread"
    elif zscore <= -entry_threshold:
        signal = "long_spread"
    elif abs(zscore) <= exit_threshold:
        signal = "exit"
    else:
        signal = "hold"

    return {"zscore": float(zscore), "signal": signal}


def estimate_half_life(spread: Sequence[float]) -> float | None:
    """Estimate Ornstein-Uhlenbeck half-life from a spread series."""
    values = np.asarray(spread, dtype=float)
    if len(values) < 3:
        return None

    lagged = values[:-1]
    delta = np.diff(values)
    design = np.column_stack([lagged, np.ones(len(lagged))])
    beta, _intercept = np.linalg.lstsq(design, delta, rcond=None)[0]
    if not np.isfinite(beta) or beta >= 0.0:
        return None

    half_life = -np.log(2.0) / float(beta)
    if not np.isfinite(half_life) or half_life <= 0.0:
        return None
    return float(half_life)
