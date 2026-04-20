import pytest
from datetime import datetime

from app.models.analysis_skill import (
    AnalysisRequest,
    AnalysisRunLimits,
    AnalysisWindow,
    canonical_metrics_for_response,
    normalize_metric_keys,
)


def test_request_validation_accepts_required_fields_and_windows():
    payload = {
        "strategy_name": "example_rsi",
        "baseline_strategy_name": "example_rsi",
        "pair": "ETH-USDT-SWAP",
        "timeframe": "1H",
        "windows": [
            {"name": "train", "start": "2026-03-01T00:00:00", "end": "2026-03-05T00:00:00"},
            {"name": "val", "start": "2026-03-05T00:00:00", "end": "2026-03-08T00:00:00"},
            {"name": "holdout", "start": "2026-03-08T00:00:00", "end": "2026-03-10T00:00:00"},
        ],
        "assumptions": {
            "initial_balance": 10000,
            "leverage": 3,
            "fee_rate": 0.0005,
            "slippage_pct": 0.05,
            "funding_rate_per_8h": 0.0001,
            "cooldown_candles": 1,
            "liquidity_impact_factor": 0.1,
            "maintenance_margin_ratio": 0.005,
            "liquidation_fee_pct": 0.002,
        },
        "search_space": {"rsi_period": [7, 21], "oversold": [20, 40], "overbought": [60, 80]},
        "top_k": 2,
        "run_limits": {
            "max_combinations": 99,
            "timeout_sec": 900,
            "retry_per_failed_job": 1,
            "partial_failure_threshold": 0.2,
        },
    }
    req = AnalysisRequest(**payload)

    assert req.top_k == 2
    names = [w.name for w in req.windows]
    assert names == ["train", "val", "holdout"]


def test_windows_out_of_order_is_invalid():
    with pytest.raises(ValueError):
        AnalysisRequest(
            strategy_name="example_rsi",
            baseline_strategy_name="example_rsi",
            pair="ETH-USDT-SWAP",
            timeframe="1H",
            windows=[
                {"name": "train", "start": "2026-03-01T00:00:00", "end": "2026-03-05T00:00:00"},
                {"name": "train", "start": "2026-03-05T00:00:00", "end": "2026-03-08T00:00:00"},
                {"name": "holdout", "start": "2026-03-08T00:00:00", "end": "2026-03-10T00:00:00"},
            ],
            assumptions={
                "initial_balance": 10000,
                "leverage": 3,
                "fee_rate": 0.0005,
                "slippage_pct": 0.05,
                "funding_rate_per_8h": 0.0001,
                "cooldown_candles": 1,
                "liquidity_impact_factor": 0.1,
                "maintenance_margin_ratio": 0.005,
                "liquidation_fee_pct": 0.002,
            },
            search_space={"x": [1, 2]},
        )


def test_run_limits_defaults_are_within_caps():
    limits = AnalysisRunLimits()
    assert limits.max_combinations == 100
    assert limits.timeout_sec == 900
    assert limits.retry_per_failed_job == 1
    assert limits.partial_failure_threshold == 0.2


def test_canonical_metrics_builder_requires_all_fields():
    normalized = canonical_metrics_for_response(
        sharpe=1.0,
        mdd=0.2,
        total_pnl=10,
        win_rate=0.4,
        trade_count=3,
    )
    assert normalized["sharpe_ratio"] == 1.0
    assert normalized["max_drawdown"] == 0.2
