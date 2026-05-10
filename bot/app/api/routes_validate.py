"""Strategy validation pipeline API routes.

POST   /api/validate/run                — trigger full validation pipeline
GET    /api/validate/progress            — current pipeline progress
GET    /api/validate/results             — latest completed results
POST   /api/validate/deploy/{strategy}   — deploy validated strategy to demo
DELETE /api/validate/cancel              — cancel running validation
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.logging_config import get_logger
from app.models.strategy_config import StrategyConfig

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["validate"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ValidateRunRequest(BaseModel):
    pairs: list[str] = Field(default=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    timeframes: list[str] = Field(default=["1H", "4H"])
    initial_balance: float = Field(default=10_000.0, gt=0)
    leverage: int = Field(default=1, ge=1, le=125)
    lookback_days: int = Field(default=180, ge=30, le=365)
    top_n: int = Field(default=3, ge=1, le=10)
    n_iterations: int = Field(default=30, ge=5, le=200)


class ValidateRunResponse(BaseModel):
    run_id: str
    status: str


class ProgressResponse(BaseModel):
    run_id: str
    phase: str
    pct: int
    message: str
    started_at: Optional[str]


class StrategyRankingOut(BaseModel):
    rank: int
    strategy_name: str
    pair: str
    timeframe: str
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_pnl: float
    trade_count: int
    composite_score: float


class OptimizedStrategyOut(BaseModel):
    strategy_name: str
    original_params: dict[str, float]
    optimized_params: dict[str, float]
    before_score: float
    after_score: float


class ValidationResultOut(BaseModel):
    run_id: str
    rankings: list[StrategyRankingOut]
    optimized: list[OptimizedStrategyOut]
    completed_at: str
    total_backtests: int
    duration_seconds: float


class DeployResponse(BaseModel):
    status: str
    message: str


class CancelResponse(BaseModel):
    cancelled: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pipeline(request: Request):
    return getattr(request.app.state, "validation_pipeline", None)


def _get_task(request: Request) -> Optional[asyncio.Task]:
    return getattr(request.app.state, "validation_task", None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/validate/run",
    response_model=ValidateRunResponse,
    summary="Trigger full validation pipeline",
)
async def run_validation(request: Request, body: ValidateRunRequest) -> ValidateRunResponse:
    # Guard: reject if already running
    existing = _get_task(request)
    if existing is not None and not existing.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A validation is already running. Cancel it first or wait for completion.",
        )

    # Lazy-create pipeline
    pipeline = _get_pipeline(request)
    if pipeline is None:
        from app.core.validation_pipeline import ValidationPipeline
        from app.db.database import AsyncSessionLocal
        from app.exchange.public_market_data import OKXPublicMarketData

        registry = getattr(request.app.state, "strategy_registry", None)
        if registry is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Strategy registry not available",
            )
        okx_client = OKXPublicMarketData()
        pipeline = ValidationPipeline(okx_client, AsyncSessionLocal, registry)
        request.app.state.validation_pipeline = pipeline

    async def _run_pipeline():
        try:
            await pipeline.run(
                pairs=body.pairs,
                timeframes=body.timeframes,
                initial_balance=body.initial_balance,
                leverage=body.leverage,
                lookback_days=body.lookback_days,
                top_n=body.top_n,
                n_iterations=body.n_iterations,
            )
        except asyncio.CancelledError:
            pipeline.progress.update(phase="cancelled", message="사용자에 의해 취소됨")
            logger.info("validation_cancelled")
        except Exception as exc:
            pipeline.progress.update(phase="error", message=str(exc)[:200])
            logger.error("validation_pipeline_error", error=str(exc))

    task = asyncio.create_task(_run_pipeline())
    request.app.state.validation_task = task

    run_id = pipeline.progress.get("run_id", "")
    logger.info("validation_triggered", run_id=run_id)
    return ValidateRunResponse(run_id=run_id, status="started")


@router.get(
    "/validate/progress",
    response_model=ProgressResponse,
    summary="Get pipeline progress",
)
async def get_progress(request: Request) -> ProgressResponse:
    pipeline = _get_pipeline(request)
    if pipeline is None:
        return ProgressResponse(run_id="", phase="idle", pct=0, message="파이프라인이 아직 실행된 적 없음", started_at=None)
    p = pipeline.progress
    return ProgressResponse(
        run_id=p.get("run_id", ""),
        phase=p.get("phase", "idle"),
        pct=p.get("pct", 0),
        message=p.get("message", ""),
        started_at=p.get("started_at"),
    )


@router.get(
    "/validate/results",
    response_model=Optional[ValidationResultOut],
    summary="Get latest validation results",
)
async def get_results(request: Request) -> Any:
    from app.core.validation_pipeline import ValidationPipeline

    data = ValidationPipeline.load_latest()
    if data is None:
        return None
    return data


@router.post(
    "/validate/deploy/{strategy_name}",
    response_model=DeployResponse,
    summary="Deploy validated strategy to demo trading",
)
async def deploy_strategy(
    request: Request,
    strategy_name: str,
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    registry = getattr(request.app.state, "strategy_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")

    # Verify strategy exists
    try:
        registry.get(strategy_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_name!r} not found")

    # Load latest results to get optimized params and best pair/timeframe
    from app.core.validation_pipeline import ValidationPipeline

    results = ValidationPipeline.load_latest()
    params: dict = {}
    pair = "BTC-USDT-SWAP"
    timeframe = "1m"

    if results:
        for r in results.get("rankings", []):
            if r["strategy_name"] == strategy_name:
                pair = r["pair"]
                timeframe = r.get("timeframe", timeframe)
                break
        for o in results.get("optimized", []):
            if o["strategy_name"] == strategy_name:
                params = o["optimized_params"]
                break

    # Upsert config in DB (matches existing routes_config pattern)
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.strategy_name == strategy_name,
            StrategyConfig.pair == pair,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.timeframe = timeframe
        existing.parameters_json = params or None
        existing.leverage = 1
        existing.is_active = True
    else:
        config = StrategyConfig(
            strategy_name=strategy_name,
            pair=pair,
            timeframe=timeframe,
            parameters_json=params or None,
            leverage=1,
            is_active=True,
        )
        db.add(config)

    await db.flush()
    logger.info(
        "strategy_deployed",
        strategy=strategy_name,
        pair=pair,
        timeframe=timeframe,
        params=params,
    )
    return DeployResponse(
        status="ok",
        message=f"{strategy_name} 전략이 {pair} ({timeframe})에 데모 배포되었습니다",
    )


@router.delete(
    "/validate/cancel",
    response_model=CancelResponse,
    summary="Cancel running validation",
)
async def cancel_validation(request: Request) -> CancelResponse:
    task = _get_task(request)
    if task is None or task.done():
        return CancelResponse(cancelled=False, message="실행 중인 검증이 없습니다")
    task.cancel()
    logger.info("validation_cancel_requested")
    return CancelResponse(cancelled=True, message="검증 취소 요청됨")
