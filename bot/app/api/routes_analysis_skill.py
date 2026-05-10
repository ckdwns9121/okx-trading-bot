"""Analysis skill API routes.

POST /api/analysis/skill/run triggers an in-process analysis experiment and
returns recommendations with baseline/replay diagnostics.
POST /api/analysis/skill/promote runs analysis and promotes a selected
recommendation into strategy config (optionally applying to running engine).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.analysis_experiment_runner import AnalysisExperimentRunner
from app.core.analysis_experiment_runner import AnalysisRunResult
from app.core.runtime_events import add_event
from app.db import repository as repo
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


class AnalysisPromoteRequest(BaseModel):
    analysis_request: AnalysisRequest
    recommendation_rank: int = Field(default=1, ge=1, le=3)
    dry_run: bool = Field(default=False)
    activate_config: bool = Field(default=True)
    apply_to_live_engine: bool = Field(default=False)
    approval_note: str = Field(default="manual_approval", min_length=2, max_length=300)


class PromotedConfigOut(BaseModel):
    strategy_name: str
    pair: str
    timeframe: str
    parameters_json: dict[str, float]
    leverage: int
    is_active: bool


class AnalysisPromoteResponse(BaseModel):
    run_id: str
    status: str
    recommendation_rank: int
    dry_run: bool
    approval_note: str
    selected_params: dict[str, float]
    config_updated: bool
    live_engine_applied: bool
    config: PromotedConfigOut


async def _persist_config(session_factory: Any, data: dict[str, Any]) -> dict[str, Any]:
    async with session_factory() as session:
        cfg = await repo.upsert_config(session, data)
        await session.commit()
        await session.refresh(cfg)
        return {
            "strategy_name": cfg.strategy_name,
            "pair": cfg.pair,
            "timeframe": cfg.timeframe,
            "parameters_json": cfg.parameters_json or {},
            "leverage": cfg.leverage,
            "is_active": cfg.is_active,
        }


async def _apply_config_to_live_engine(request: Request, data: dict[str, Any]) -> bool:
    live_engine = getattr(request.app.state, "live_engine", None)
    if live_engine is None:
        return False
    if not getattr(live_engine, "is_running", False):
        return False

    pair = str(data["pair"])
    pair_statuses = live_engine.pair_manager.get_status()
    if pair in pair_statuses:
        await live_engine.pair_manager.remove_pair(pair)

    if bool(data.get("is_active", False)):
        await live_engine.pair_manager.add_pair(
            pair=pair,
            strategy_name=str(data["strategy_name"]),
            leverage=int(data["leverage"]),
            timeframe=str(data["timeframe"]),
            params=dict(data.get("parameters_json") or {}),
        )
        return True
    return False


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


@router.post(
    "/skill/promote",
    response_model=AnalysisPromoteResponse,
    summary="Run analysis and promote selected recommendation into config",
)
async def run_and_promote_analysis_skill(
    body: AnalysisPromoteRequest,
    request: Request,
) -> AnalysisPromoteResponse:
    if body.apply_to_live_engine and not body.activate_config:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="apply_to_live_engine=true requires activate_config=true",
        )

    analysis = await run_analysis_skill(body.analysis_request, request)
    if body.recommendation_rank > analysis.recommendation_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"recommendation_rank {body.recommendation_rank} exceeds "
                f"available recommendations ({analysis.recommendation_count})"
            ),
        )

    selected = next(
        rec for rec in analysis.recommendations if rec.rank == body.recommendation_rank
    )
    config_payload: dict[str, Any] = {
        "strategy_name": body.analysis_request.strategy_name,
        "pair": body.analysis_request.pair,
        "timeframe": body.analysis_request.timeframe,
        "parameters_json": dict(selected.params),
        "leverage": body.analysis_request.assumptions.leverage,
        "is_active": bool(body.activate_config),
    }

    if body.dry_run:
        add_event(
            event="analysis_skill_promote_preview",
            pair=config_payload["pair"],
            strategy=config_payload["strategy_name"],
            timeframe=config_payload["timeframe"],
            details={
                "run_id": analysis.run_id,
                "recommendation_rank": body.recommendation_rank,
                "approval_note": body.approval_note,
                "selected_params": config_payload["parameters_json"],
            },
            message="Analysis recommendation preview generated",
        )
        return AnalysisPromoteResponse(
            run_id=analysis.run_id,
            status=analysis.status,
            recommendation_rank=body.recommendation_rank,
            dry_run=True,
            approval_note=body.approval_note,
            selected_params=dict(selected.params),
            config_updated=False,
            live_engine_applied=False,
            config=PromotedConfigOut(**config_payload),
        )

    try:
        session_factory = request.app.state.db_session_factory
    except AttributeError:
        from app.db.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    persisted = await _persist_config(session_factory, config_payload)
    live_engine_applied = False
    if body.apply_to_live_engine:
        try:
            live_engine_applied = await _apply_config_to_live_engine(
                request, persisted
            )
        except Exception as exc:
            logger.error("analysis_skill_live_apply_failed", error=str(exc), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Config saved but failed to apply to live engine: {exc}",
            ) from exc

    add_event(
        event="analysis_skill_promoted",
        pair=persisted["pair"],
        strategy=persisted["strategy_name"],
        timeframe=persisted["timeframe"],
        details={
            "run_id": analysis.run_id,
            "recommendation_rank": body.recommendation_rank,
            "approval_note": body.approval_note,
            "apply_to_live_engine": body.apply_to_live_engine,
            "live_engine_applied": live_engine_applied,
            "selected_params": persisted["parameters_json"],
        },
        message="Analysis recommendation promoted to strategy config",
    )
    return AnalysisPromoteResponse(
        run_id=analysis.run_id,
        status=analysis.status,
        recommendation_rank=body.recommendation_rank,
        dry_run=False,
        approval_note=body.approval_note,
        selected_params=dict(selected.params),
        config_updated=True,
        live_engine_applied=live_engine_applied,
        config=PromotedConfigOut(**persisted),
    )
