import pytest

from app.core import analysis_scoring
from app.core.analysis_scoring import score_candidate, score_window_metrics, normalize_metrics


def test_normalize_metrics_accepts_aliases_and_requires_all_keys():
    normalized = normalize_metrics({"sharpe": 1.2, "mdd": 0.33, "total_pnl": 100.0, "win_rate": 0.55, "trade_count": 20})
    assert normalized["sharpe_ratio"] == 1.2
    assert normalized["max_drawdown"] == 0.33
    assert normalized["total_pnl"] == 100.0


def test_normalize_metrics_rejects_unknown_key():
    with pytest.raises(ValueError):
        normalize_metrics({"foo": 1, "total_pnl": 0, "sharpe_ratio": 1.0, "max_drawdown": 0.1, "win_rate": 0.5, "trade_count": 3})


def test_score_window_metrics_bounds_and_shape():
    score = score_window_metrics({
        "total_pnl": 10.0,
        "sharpe_ratio": 1.0,
        "max_drawdown": 0.1,
        "win_rate": 0.5,
        "trade_count": 100,
    })
    assert 0.0 <= score <= 1.0


def test_score_candidate_uses_train_val_holdout_windows():
    metrics_by_window = {
        "train": {"total_pnl": 12, "sharpe_ratio": 0.5, "max_drawdown": 0.1, "win_rate": 0.5, "trade_count": 8},
        "val": {"total_pnl": 8, "sharpe_ratio": 0.4, "max_drawdown": 0.2, "win_rate": 0.4, "trade_count": 6},
        "holdout": {"total_pnl": 6, "sharpe_ratio": 0.6, "max_drawdown": 0.15, "win_rate": 0.45, "trade_count": 10},
    }
    score = score_candidate(metrics_by_window)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0

    breakdown = analysis_scoring.score_and_breakdown(metrics_by_window)
    assert breakdown.score == score
    assert breakdown.trade_count == 10.0
