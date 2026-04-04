"""Configuration and health-check API routes.

GET  /api/config             — list all strategy configs
PUT  /api/config             — upsert a strategy config
GET  /api/config/strategies  — list available strategy names from registry
GET  /api/health             — deep health check
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.logging_config import get_logger
from app.models.strategy_config import StrategyConfig

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["config"])

_ALLOWED_TIMEFRAMES = {
    "1m", "3m", "5m", "15m", "30m",
    "1H", "2H", "4H", "6H", "12H",
    "1D",
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class StrategyConfigOut(BaseModel):
    id: int
    strategy_name: str
    pair: str
    timeframe: str
    parameters_json: Optional[dict[str, Any]]
    leverage: int
    is_active: bool

    model_config = {"from_attributes": True}


class StrategyConfigUpsert(BaseModel):
    strategy_name: str = Field(..., description="Registered strategy name")
    pair: str = Field(..., description="Instrument ID, e.g. BTC-USDT-SWAP")
    timeframe: str = Field(default="1m", description="Candle timeframe, e.g. 1m, 1H, 4H")
    parameters_json: Optional[dict[str, Any]] = Field(default=None)
    leverage: int = Field(default=1, ge=1, le=125)
    is_active: bool = Field(default=False)

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, value: str) -> str:
        tf = value.strip()
        if tf not in _ALLOWED_TIMEFRAMES:
            allowed = ", ".join(sorted(_ALLOWED_TIMEFRAMES))
            raise ValueError(f"Unsupported timeframe {value!r}. Allowed: {allowed}")
        return tf


class AvailableStrategiesResponse(BaseModel):
    strategies: list[str]


class TradingTasksStatus(BaseModel):
    active: int
    failed: int
    stopped: int


class OKXApiStatus(BaseModel):
    status: str
    mode: str


class HealthResponse(BaseModel):
    db: str
    okx_api: OKXApiStatus
    trading_tasks: TradingTasksStatus
    circuit_breaker: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    response_model=list[StrategyConfigOut],
    summary="List all strategy configurations",
)
async def list_strategy_configs(
    db: AsyncSession = Depends(get_db),
) -> list[StrategyConfigOut]:
    result = await db.execute(
        select(StrategyConfig).order_by(
            StrategyConfig.strategy_name,
            StrategyConfig.pair,
            StrategyConfig.timeframe,
        )
    )
    configs = result.scalars().all()
    return [StrategyConfigOut.model_validate(c) for c in configs]


@router.put(
    "/config",
    response_model=StrategyConfigOut,
    status_code=status.HTTP_200_OK,
    summary="Upsert a strategy configuration",
)
async def upsert_strategy_config(
    body: StrategyConfigUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StrategyConfigOut:
    # Validate strategy is known.
    registry = request.app.state.strategy_registry
    if body.strategy_name not in registry.list_all():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown strategy {body.strategy_name!r}. Available: {registry.list_all()}",
        )

    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.strategy_name == body.strategy_name,
            StrategyConfig.pair == body.pair,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.timeframe = body.timeframe
        existing.parameters_json = body.parameters_json
        existing.leverage = body.leverage
        existing.is_active = body.is_active
        config = existing
        logger.info(
            "strategy_config_updated",
            strategy=body.strategy_name,
            pair=body.pair,
        )
    else:
        config = StrategyConfig(
            strategy_name=body.strategy_name,
            pair=body.pair,
            timeframe=body.timeframe,
            parameters_json=body.parameters_json,
            leverage=body.leverage,
            is_active=body.is_active,
        )
        db.add(config)
        logger.info(
            "strategy_config_created",
            strategy=body.strategy_name,
            pair=body.pair,
        )

    await db.flush()
    return StrategyConfigOut.model_validate(config)


@router.get(
    "/config/strategies",
    response_model=AvailableStrategiesResponse,
    summary="List available strategy names from the registry",
)
async def list_available_strategies(request: Request) -> AvailableStrategiesResponse:
    registry = request.app.state.strategy_registry
    return AvailableStrategiesResponse(strategies=registry.list_all())


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Deep health check",
)
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    from app.config import settings

    # --- DB check ---
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health_check_db_failed", error=str(exc))
        db_status = "error"

    # --- OKX API check ---
    okx_api_status = "ok"
    okx_client = getattr(request.app.state, "okx_client", None)
    if okx_client is None:
        okx_api_status = "error"
    else:
        try:
            await okx_client.get_account_balance()
        except Exception as exc:
            logger.warning("health_check_okx_failed", error=str(exc))
            okx_api_status = "error"

    # --- Trading tasks ---
    trading_tasks = TradingTasksStatus(active=0, failed=0, stopped=0)
    engine = getattr(request.app.state, "live_engine", None)
    if engine is not None:
        try:
            status = engine.get_status()
            pairs = status.get("pairs", {})
            active = sum(1 for p in pairs.values() if p.get("status") == "running")
            failed = sum(1 for p in pairs.values() if p.get("status") == "failed")
            stopped = sum(1 for p in pairs.values() if p.get("status") == "stopped")
            trading_tasks = TradingTasksStatus(active=active, failed=failed, stopped=stopped)
        except Exception as exc:
            logger.warning("health_check_engine_failed", error=str(exc))

    # --- Circuit breaker ---
    cb_status = "ok"
    cb = getattr(request.app.state, "circuit_breaker", None)
    if cb is not None:
        try:
            cb_status = "tripped" if cb.is_tripped else "ok"
        except Exception as exc:
            logger.warning("health_check_cb_failed", error=str(exc))
            cb_status = "error"

    return HealthResponse(
        db=db_status,
        okx_api=OKXApiStatus(status=okx_api_status, mode=settings.OKX_MODE),
        trading_tasks=trading_tasks,
        circuit_breaker=cb_status,
    )
