import numpy as np
import pytest

from app.core.quant_research import (
    classify_volatility_regime,
    estimate_half_life,
    price_ratio,
    rank_candidates_by_survival,
    rolling_correlation_stability,
    summarize_walk_forward_evaluation,
    volatility_profile_matches,
    zscore_signal,
)


def metrics(
    *,
    total_pnl: float,
    sharpe_ratio: float,
    max_drawdown: float,
    win_rate: float,
    trade_count: float,
) -> dict[str, float]:
    return {
        "total_pnl": total_pnl,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "trade_count": trade_count,
    }


def test_walk_forward_summary_aggregates_complete_fixed_windows():
    folds = [
        {
            "train_window": {"start": "2026-01-01T00:00:00", "end": "2026-01-10T00:00:00"},
            "evaluation_window": {"start": "2026-01-10T00:00:00", "end": "2026-01-15T00:00:00"},
            "train_params": {"param_a": 14, "param_b": 20},
            "evaluation_params": {"param_a": 14, "param_b": 20},
            "train_metrics": metrics(total_pnl=8.0, sharpe_ratio=1.0, max_drawdown=0.12, win_rate=0.51, trade_count=10),
            "evaluation_metrics": metrics(total_pnl=4.0, sharpe_ratio=0.7, max_drawdown=0.10, win_rate=0.55, trade_count=6),
        },
        {
            "train_window": {"start": "2026-01-15T00:00:00", "end": "2026-01-25T00:00:00"},
            "evaluation_window": {"start": "2026-01-25T00:00:00", "end": "2026-01-30T00:00:00"},
            "train_params": {"param_a": 12, "param_b": 18},
            "evaluation_params": {"param_a": 12, "param_b": 18},
            "train_metrics": metrics(total_pnl=5.0, sharpe_ratio=0.8, max_drawdown=0.15, win_rate=0.48, trade_count=8),
            "evaluation_metrics": metrics(total_pnl=2.0, sharpe_ratio=0.5, max_drawdown=0.20, win_rate=0.45, trade_count=4),
        },
    ]

    summary = summarize_walk_forward_evaluation(folds, expected_folds=2)

    assert summary.complete is True
    assert summary.status == "ok"
    assert summary.fold_count == 2
    assert summary.total_evaluation_pnl == pytest.approx(6.0)
    assert summary.average_evaluation_sharpe == pytest.approx(0.6)
    assert summary.worst_evaluation_drawdown == pytest.approx(0.20)
    assert summary.average_evaluation_win_rate == pytest.approx(0.5)
    assert summary.average_evaluation_trade_count == pytest.approx(5.0)


def test_walk_forward_summary_fails_closed_on_incomplete_data():
    folds = [
        {
            "train_window": {"start": "2026-01-01T00:00:00", "end": "2026-01-10T00:00:00"},
            "evaluation_window": {"start": "2026-01-10T00:00:00", "end": "2026-01-15T00:00:00"},
            "train_params": {"param_a": 14},
            "train_metrics": metrics(total_pnl=8.0, sharpe_ratio=1.0, max_drawdown=0.12, win_rate=0.51, trade_count=10),
            "evaluation_metrics": {"total_pnl": 4.0},
        }
    ]

    summary = summarize_walk_forward_evaluation(folds, expected_folds=1)

    assert summary.complete is False
    assert summary.status == "incomplete_data"
    assert summary.failure_reason == "missing_metrics"


def test_walk_forward_summary_rejects_evaluation_window_retuning():
    folds = [
        {
            "train_window": {"start": "2026-01-01T00:00:00", "end": "2026-01-10T00:00:00"},
            "evaluation_window": {"start": "2026-01-10T00:00:00", "end": "2026-01-15T00:00:00"},
            "train_params": {"param_a": 14},
            "evaluation_params": {"param_a": 10},
            "train_metrics": metrics(total_pnl=8.0, sharpe_ratio=1.0, max_drawdown=0.12, win_rate=0.51, trade_count=10),
            "evaluation_metrics": metrics(total_pnl=4.0, sharpe_ratio=0.7, max_drawdown=0.10, win_rate=0.55, trade_count=6),
        }
    ]

    summary = summarize_walk_forward_evaluation(folds, expected_folds=1)

    assert summary.complete is False
    assert summary.status == "evaluation_window_retuned"
    assert summary.failure_reason == "evaluation_params_changed"


def test_survival_rank_uses_monte_carlo_fields():
    ranked = rank_candidates_by_survival(
        [
            {
                "candidate_id": "durable",
                "initial_balance": 1000.0,
                "median_final_balance": 1250.0,
                "p5_final_balance": 980.0,
                "p95_max_drawdown": 0.18,
                "ruin_probability": 0.01,
            },
            {
                "candidate_id": "fragile",
                "initial_balance": 1000.0,
                "median_final_balance": 1400.0,
                "p5_final_balance": 620.0,
                "p95_max_drawdown": 0.48,
                "ruin_probability": 0.22,
            },
        ]
    )

    assert [row["candidate_id"] for row in ranked] == ["durable", "fragile"]
    assert ranked[0]["survival_rank"] == 1
    assert ranked[0]["survival_score"] > ranked[1]["survival_score"]


def test_volatility_regime_classification_and_profile_matching():
    low = classify_volatility_regime(bb_width_pct=1.2, atr_pct=0.7)
    normal = classify_volatility_regime(bb_width_pct=3.5, atr_pct=1.5)
    high = classify_volatility_regime(bb_width_pct=9.2, atr_pct=3.5)

    assert low.regime == "low"
    assert normal.regime == "normal"
    assert high.regime == "high"
    assert volatility_profile_matches("normal", "normal") is True
    assert volatility_profile_matches("normal", "low") is False
    assert volatility_profile_matches("any", "high") is True


def test_stat_arb_baseline_helpers_cover_ratio_correlation_zscore_and_half_life():
    base = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    quote = np.array([50.0, 50.5, 51.0, 51.5, 52.0])
    ratio = price_ratio(base, quote)
    assert np.allclose(ratio, np.array([2.0, 2.0, 2.0, 2.0, 2.0]))

    left = np.array([1, 2, 3, 4, 5, 6], dtype=float)
    right = np.array([2, 4, 6, 8, 10, 12], dtype=float)
    stability = rolling_correlation_stability(left, right, window=3)
    assert stability["mean_correlation"] == pytest.approx(1.0)
    assert stability["stability_score"] == pytest.approx(1.0)

    signal = zscore_signal([0.0, 0.1, -0.1, 0.05, 3.0], window=5, entry_threshold=1.5, exit_threshold=0.25)
    assert signal["signal"] == "short_spread"
    assert float(signal["zscore"]) > 1.5

    mean_reverting = [5.0, 3.0, 2.4, 1.8, 1.4, 1.1, 0.9, 0.7, 0.55, 0.4]
    half_life = estimate_half_life(mean_reverting)
    assert half_life is not None
    assert half_life > 0.0
