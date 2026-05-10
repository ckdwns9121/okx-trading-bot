from datetime import datetime
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("OKX_API_KEY", "test-key")
os.environ.setdefault("OKX_SECRET", "test-secret")
os.environ.setdefault("OKX_PASSPHRASE", "test-passphrase")

from scripts.run_all_strategy_backtest_comparison import (
    monte_carlo_survival_summary,
    primary_survival_metrics,
    conclusion_lines,
    summarize,
    verdict_for,
)


def test_summarize_ranks_raw_pnl_but_marks_high_drawdown_as_high_risk():
    results = [
        {
            "strategy": "raw_winner",
            "status": "ok",
            "total_pnl": 1000.0,
            "max_drawdown": 0.75,
            "profit_factor": 1.2,
            "sharpe_ratio": 0.5,
            "win_rate": 0.5,
            "trade_count": 10,
            "pair": "ETH-USDT-SWAP",
            "timeframe": "15m",
            "p95_max_drawdown": 0.0,
            "ruin_probability": 0.0,
            "p5_final_balance": 10000.0,
        },
        {
            "strategy": "stable",
            "status": "ok",
            "total_pnl": 200.0,
            "max_drawdown": 0.2,
            "profit_factor": 1.4,
            "sharpe_ratio": 1.0,
            "win_rate": 0.6,
            "trade_count": 5,
            "pair": "BTC-USDT-SWAP",
            "timeframe": "1H",
            "p95_max_drawdown": 0.0,
            "ruin_probability": 0.0,
            "p5_final_balance": 10000.0,
        },
    ]

    summaries = summarize(results)

    by_strategy = {row["strategy"]: row for row in summaries}
    assert by_strategy["raw_winner"]["verdict"] == "고위험 관찰"
    assert by_strategy["stable"]["verdict"] == "paper 후보"
    assert summaries[0]["strategy"] == "stable"
    assert "survival_rank" in by_strategy["stable"]


def test_verdict_for_rejects_negative_total_pnl():
    verdict = verdict_for(
        {
            "ok_runs": 3,
            "positive_runs": 1,
            "total_pnl": -10.0,
            "positive_rate_pct": 33.3,
            "max_drawdown_pct": 5.0,
        }
    )

    assert verdict == "탈락/보류"


def test_verdict_for_blocks_monte_carlo_ruin_risk():
    verdict = verdict_for(
        {
            "ok_runs": 3,
            "positive_runs": 3,
            "total_pnl": 1000.0,
            "positive_rate_pct": 100.0,
            "max_drawdown_pct": 5.0,
            "max_ruin_probability": 0.02,
            "max_p95_max_drawdown_pct": 10.0,
        }
    )

    assert verdict == "실거래 금지"


def test_monte_carlo_survival_summary_exposes_position_size_scenarios():
    now = datetime(2026, 1, 1)
    trades = [
        SimpleNamespace(pnl=100.0, entry_time=now, exit_time=now),
        SimpleNamespace(pnl=-50.0, entry_time=now, exit_time=now),
        SimpleNamespace(pnl=25.0, entry_time=now, exit_time=now),
    ]

    summary = monte_carlo_survival_summary(
        trades,
        initial_balance=10_000.0,
        position_size_pcts=(5.0, 10.0),
        n_simulations=25,
    )
    primary = primary_survival_metrics(summary, position_size_pct=10.0)

    assert set(summary) == {"5", "10"}
    assert summary["10"]["n_simulations"] == 25
    assert {"p95_max_drawdown", "ruin_probability", "p5_final_balance"} <= set(primary)


def test_primary_survival_metrics_fails_closed_for_missing_scenario():
    with pytest.raises(ValueError, match="scenario 25% is missing"):
        primary_survival_metrics(
            {"5": {"p95_max_drawdown": 0.1, "ruin_probability": 0.0, "p5_final_balance": 9000.0}},
            position_size_pct=25.0,
        )


def test_conclusion_lines_warn_when_raw_winner_has_large_drawdown():
    payload = {
        "summaries": [
            {
                "strategy": "example_rsi",
                "verdict": "고위험 관찰",
                "total_pnl": 1000.0,
                "max_drawdown_pct": 97.44,
                "positive_runs": 4,
                "ok_runs": 6,
            },
            {
                "strategy": "rsi_bollinger_regime",
                "verdict": "고위험 관찰",
                "total_pnl": 100.0,
                "max_drawdown_pct": 68.49,
                "positive_runs": 5,
                "ok_runs": 6,
            },
        ]
    }

    lines = conclusion_lines(payload)

    assert any("example_rsi" in line and "바로 demo/live 후보로 보지 않는다" in line for line in lines)
    assert any("risk_profile=limited" in line for line in lines)
