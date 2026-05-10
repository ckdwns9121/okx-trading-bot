from types import SimpleNamespace

import pytest

from app.api.routes_analysis_skill import (
    run_analysis_skill,
    run_and_promote_analysis_skill,
    AnalysisPromoteRequest,
)
from app.core.analysis_experiment_runner import AnalysisExperimentRunner, AnalysisRunResult, MetricsByWindowResult, RecommendationResult
from app.models.analysis_skill import AnalysisRequest


class _Registry:
    def list_all(self):
        return ["example_rsi", "example_sma_cross"]


class _Request:
    def __init__(self):
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                strategy_registry=_Registry(),
                okx_client=object(),
            )
        )


@pytest.mark.asyncio
async def test_route_analysis_skill_response_shape(monkeypatch):
    req_body = {
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
            "leverage": 2,
            "fee_rate": 0.0005,
            "slippage_pct": 0.05,
            "funding_rate_per_8h": 0.0001,
            "cooldown_candles": 1,
            "liquidity_impact_factor": 0.1,
            "maintenance_margin_ratio": 0.005,
            "liquidation_fee_pct": 0.002,
        },
        "search_space": {"rsi_period": [7, 21], "oversold": [20, 40], "overbought": [60, 80]},
        "top_k": 1,
    }

    async def _fake_run(self, _: AnalysisRequest):
        return AnalysisRunResult(
            run_id="run-123",
            status="ok",
            failures={"failed_combinations": 0, "failure_ratio": 0.0, "degraded_mode": False},
            baseline={
                "metrics_by_window": {
                    "train": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "val": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "holdout": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                }
            },
            recommendations=[
                RecommendationResult(
                    rank=1,
                    params={"rsi_period": 10},
                    score=0.75,
                    metrics_by_window=MetricsByWindowResult(
                        train={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        val={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        holdout={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                    ),
                    baseline_delta_by_window={
                        "train": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "val": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "holdout": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                    },
                    replay_pass=True,
                    replay_delta={"total_pnl": 0, "sharpe_ratio": 0, "max_drawdown": 0, "win_rate": 0, "trade_count": 0},
                )
            ],
        )

    monkeypatch.setattr(AnalysisExperimentRunner, "run", _fake_run)

    body = AnalysisRequest(**req_body)
    response = await run_analysis_skill(body, _Request())

    assert response.run_id == "run-123"
    assert response.status == "ok"
    assert response.recommendation_count == 1
    assert response.recommendations[0].metrics_by_window.holdout["trade_count"] == 3
    assert response.baseline.metrics_by_window.train["total_pnl"] == 1


@pytest.mark.asyncio
async def test_promote_analysis_skill_dry_run(monkeypatch):
    req_body = {
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
        "top_k": 1,
    }

    async def _fake_run(self, _: AnalysisRequest):
        return AnalysisRunResult(
            run_id="run-preview",
            status="ok",
            failures={"failed_combinations": 0, "failure_ratio": 0.0, "degraded_mode": False},
            baseline={
                "metrics_by_window": {
                    "train": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "val": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "holdout": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                }
            },
            recommendations=[
                RecommendationResult(
                    rank=1,
                    params={"rsi_period": 12},
                    score=0.8,
                    metrics_by_window=MetricsByWindowResult(
                        train={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        val={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        holdout={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                    ),
                    baseline_delta_by_window={
                        "train": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "val": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "holdout": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                    },
                    replay_pass=True,
                    replay_delta={"total_pnl": 0, "sharpe_ratio": 0, "max_drawdown": 0, "win_rate": 0, "trade_count": 0},
                )
            ],
        )

    monkeypatch.setattr(AnalysisExperimentRunner, "run", _fake_run)

    body = AnalysisPromoteRequest(
        analysis_request=AnalysisRequest(**req_body),
        recommendation_rank=1,
        dry_run=True,
        activate_config=True,
        apply_to_live_engine=False,
        approval_note="preview only",
    )
    response = await run_and_promote_analysis_skill(body, _Request())
    assert response.run_id == "run-preview"
    assert response.dry_run is True
    assert response.config_updated is False
    assert response.config.parameters_json["rsi_period"] == 12


@pytest.mark.asyncio
async def test_promote_analysis_skill_persist_and_apply(monkeypatch):
    req_body = {
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
            "leverage": 4,
            "fee_rate": 0.0005,
            "slippage_pct": 0.05,
            "funding_rate_per_8h": 0.0001,
            "cooldown_candles": 1,
            "liquidity_impact_factor": 0.1,
            "maintenance_margin_ratio": 0.005,
            "liquidation_fee_pct": 0.002,
        },
        "search_space": {"rsi_period": [7, 21], "oversold": [20, 40], "overbought": [60, 80]},
        "top_k": 1,
    }

    async def _fake_run(self, _: AnalysisRequest):
        return AnalysisRunResult(
            run_id="run-apply",
            status="ok",
            failures={"failed_combinations": 0, "failure_ratio": 0.0, "degraded_mode": False},
            baseline={
                "metrics_by_window": {
                    "train": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "val": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                    "holdout": {"total_pnl": 1, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.1, "trade_count": 2},
                }
            },
            recommendations=[
                RecommendationResult(
                    rank=1,
                    params={"rsi_period": 15, "oversold": 30},
                    score=0.81,
                    metrics_by_window=MetricsByWindowResult(
                        train={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        val={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                        holdout={"total_pnl": 2, "sharpe_ratio": 1, "max_drawdown": 0.1, "win_rate": 0.2, "trade_count": 3},
                    ),
                    baseline_delta_by_window={
                        "train": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "val": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                        "holdout": {"total_pnl": 1, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.1, "trade_count": 1},
                    },
                    replay_pass=True,
                    replay_delta={"total_pnl": 0, "sharpe_ratio": 0, "max_drawdown": 0, "win_rate": 0, "trade_count": 0},
                )
            ],
        )

    captured = {}

    async def _fake_persist(_factory, data):
        captured["persist"] = dict(data)
        return dict(data)

    async def _fake_apply(_request, data):
        captured["apply"] = dict(data)
        return True

    monkeypatch.setattr(AnalysisExperimentRunner, "run", _fake_run)
    monkeypatch.setattr("app.api.routes_analysis_skill._persist_config", _fake_persist)
    monkeypatch.setattr("app.api.routes_analysis_skill._apply_config_to_live_engine", _fake_apply)

    req = _Request()
    req.app.state.db_session_factory = object()
    body = AnalysisPromoteRequest(
        analysis_request=AnalysisRequest(**req_body),
        recommendation_rank=1,
        dry_run=False,
        activate_config=True,
        apply_to_live_engine=True,
        approval_note="approved",
    )
    response = await run_and_promote_analysis_skill(body, req)

    assert response.run_id == "run-apply"
    assert response.config_updated is True
    assert response.live_engine_applied is True
    assert captured["persist"]["leverage"] == 4
    assert captured["apply"]["parameters_json"]["rsi_period"] == 15
