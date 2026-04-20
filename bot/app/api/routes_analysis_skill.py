"""Analysis skill API routes.

POST /api/analysis/skill/run triggers an in-process analysis experiment and
returns recommendations with baseline/replay diagnostics.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.core.analysis_experiment_runner import AnalysisExperimentRunner
from app.core.analysis_experiment_runner import AnalysisRunResult
from app.logging_config import get_logger
from app.models.analysis_skill import (
    AnalysisRequest,
    AnalysisResponse,
    BaselineResult,
    MetricsByWindow,
    Recommendation,
    RunFailures,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis_skill"])


def _to_dict_window(metrics: dict[str, float]) -> dict[str, float]:
    # Keep the canonical metric schema only.
    return {
        "total_pnl": float(metrics["total_pnl"]),
        "sharpe_ratio": float(metrics["sharpe_ratio"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "win_rate": float(metrics["win_rate"]),
        "trade_count": float(metrics["trade_count"]),
    }


@router.post(
    "/skill/run",
    response_model=AnalysisResponse,
    summary="Run analysis skill recommendation experiment",
)
async def run_analysis_skill(body: AnalysisRequest, request: Request) -> AnalysisResponse:
    # Validate strategy existence before heavy work.
    registry = request.app.state.strategy_registry
    for name in (body.strategy_name, body.baseline_strategy_name):
        if name not in registry.list_all():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown strategy {name!r}. Available: {registry.list_all()}",
            )

    try:
        session_factory = request.app.state.db_session_factory
    except AttributeError:
        from app.db.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    runner = AnalysisExperimentRunner(request.app.state.okx_client, session_factory)
    try:
        result: AnalysisRunResult = await runner.run(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("analysis_skill_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="analysis run failed") from exc

    recs: list[Recommendation] = []
    for rec in result.recommendations:
        recs.append(
            Recommendation(
                rank=rec.rank,
                params=rec.params,
                metrics_by_window=MetricsByWindow(
                    train=_to_dict_window(rec.metrics_by_window.train),
                    val=_to_dict_window(rec.metrics_by_window.val),
                    holdout=_to_dict_window(rec.metrics_by_window.holdout),
                ),
                baseline_delta_by_window=rec.baseline_delta_by_window,
                replay_pass=rec.replay_pass,
                replay_delta=rec.replay_delta,
            )
        )

    baseline_window = result.baseline["metrics_by_window"]
    failures = RunFailures(**result.failures)
    return AnalysisResponse(
        run_id=result.run_id,
        status=result.status,
        recommendation_count=len(recs),
        recommendations=recs,
        baseline=BaselineResult(
            metrics_by_window=MetricsByWindow(
                train=_to_dict_window(baseline_window["train"]),
                val=_to_dict_window(baseline_window["val"]),
                holdout=_to_dict_window(baseline_window["holdout"]),
            )
        ),
        failures=failures,
    )
