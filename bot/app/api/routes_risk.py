"""Risk API: kill switch control, pre-trade limits, reconciliation, TCA."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.execution_quality import ExecutionQualityLog
from app.core.reconciliation import run_reconciliation
from app.core.risk_gate import KillSwitch, RiskLimits, build_risk_gate_from_settings
from app.db.database import get_db
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk"])


class KillSwitchState(BaseModel):
    tripped: bool
    reason: str | None = None
    source: str | None = None
    changed_at: str | None = None


class RiskStatusResponse(BaseModel):
    kill_switch: KillSwitchState
    limits: dict[str, Any]
    kill_switch_file: str
    execution_log_file: str


class TripRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ReconciliationResponse(BaseModel):
    checked_at: str
    ok: bool
    critical: bool
    local_position_count: int
    exchange_position_count: int
    kill_switch_tripped: bool
    discrepancies: list[dict[str, Any]]


def _kill_switch() -> KillSwitch:
    return KillSwitch(settings.RISK_KILL_SWITCH_FILE)


def _limits_payload() -> dict[str, Any]:
    limits = RiskLimits(
        max_order_notional_usd=float(settings.RISK_MAX_ORDER_NOTIONAL_USD),
        max_instrument_notional_usd=float(settings.RISK_MAX_INSTRUMENT_NOTIONAL_USD),
        max_total_exposure_usd=float(settings.RISK_MAX_TOTAL_EXPOSURE_USD),
        max_price_deviation_pct=float(settings.RISK_MAX_PRICE_DEVIATION_PCT),
        max_daily_loss_usd=float(settings.MAX_DAILY_LOSS_USD),
        max_orders_per_minute=int(settings.RISK_MAX_ORDERS_PER_MINUTE),
    )
    return asdict(limits)


@router.get("/status", response_model=RiskStatusResponse, summary="Risk gate status")
async def get_risk_status() -> RiskStatusResponse:
    return RiskStatusResponse(
        kill_switch=KillSwitchState(**_kill_switch().status()),
        limits=_limits_payload(),
        kill_switch_file=str(settings.RISK_KILL_SWITCH_FILE),
        execution_log_file=str(settings.RISK_EXECUTION_LOG_FILE),
    )


@router.post(
    "/kill-switch/trip",
    response_model=KillSwitchState,
    summary="Trip the kill switch (block all new entries)",
)
async def trip_kill_switch(payload: TripRequest) -> KillSwitchState:
    state = _kill_switch().trip(reason=payload.reason, source="api")
    logger.warning("kill_switch_tripped", reason=payload.reason, source="api")
    return KillSwitchState(**{k: state.get(k) for k in ("tripped", "reason", "source", "changed_at")})


@router.post(
    "/kill-switch/reset",
    response_model=KillSwitchState,
    summary="Reset the kill switch (allow trading again)",
)
async def reset_kill_switch() -> KillSwitchState:
    state = _kill_switch().reset(source="api")
    logger.warning("kill_switch_reset", source="api")
    return KillSwitchState(**{k: state.get(k) for k in ("tripped", "reason", "source", "changed_at")})


@router.get(
    "/reconciliation",
    response_model=ReconciliationResponse,
    summary="Compare local book vs OKX positions",
)
async def get_reconciliation(
    request: Request,
    trip_on_critical: bool = Query(default=False),
    size_tolerance_pct: float = Query(default=0.5, ge=0.0, le=50.0),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationResponse:
    okx_client = getattr(request.app.state, "okx_client", None)
    if okx_client is None:
        raise HTTPException(status_code=503, detail="OKX client is not initialised")

    kill_switch = _kill_switch()
    try:
        report = await run_reconciliation(
            okx_client=okx_client,
            session=db,
            kill_switch=kill_switch,
            size_tolerance_pct=size_tolerance_pct,
            trip_on_critical=trip_on_critical,
        )
    except Exception as exc:
        logger.error("reconciliation_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"reconciliation failed: {exc}") from exc

    payload = report.to_payload()
    return ReconciliationResponse(
        **payload,
        kill_switch_tripped=kill_switch.is_tripped(),
    )


@router.get("/execution-quality", summary="Execution quality (TCA) summary")
async def get_execution_quality(
    limit: int | None = Query(default=None, ge=1, le=10000),
) -> dict[str, Any]:
    log = ExecutionQualityLog(settings.RISK_EXECUTION_LOG_FILE)
    return log.summary(limit=limit)
