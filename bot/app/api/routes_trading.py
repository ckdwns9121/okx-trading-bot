"""Trading control API routes.

POST /api/trading/start                — start live trading engine
POST /api/trading/stop                 — stop live trading engine
GET  /api/trading/status               — per-pair engine status
POST /api/trading/reset-circuit-breaker — reset circuit breaker
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_events import add_event, list_events
from app.db.database import get_db
from app.logging_config import get_logger
from app.models.runtime_event import RuntimeEvent

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["trading"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TradingStartResponse(BaseModel):
    status: str
    message: str


class TradingStopResponse(BaseModel):
    status: str
    message: str


class PairStatus(BaseModel):
    pair: str
    state: str
    strategy: str
    timeframe: str | None = None
    error: str | None = None


class TradingStatusResponse(BaseModel):
    running: bool
    pairs: list[PairStatus]


class CircuitBreakerResetResponse(BaseModel):
    status: str
    message: str


class TelegramTestResponse(BaseModel):
    status: str
    message: str


class TradingLogEvent(BaseModel):
    id: int
    timestamp: str
    level: str
    event: str
    pair: str | None = None
    strategy: str | None = None
    timeframe: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TradingLogsResponse(BaseModel):
    items: list[TradingLogEvent]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_live_engine(request: Request) -> Any:
    """Return the live_engine from app state, or None if not initialised."""
    return getattr(request.app.state, "live_engine", None)


def _get_circuit_breaker(request: Request) -> Any:
    """Return the circuit_breaker from app state, or None if not initialised."""
    return getattr(request.app.state, "circuit_breaker", None)


def _get_telegram_notifier(request: Request) -> Any:
    """Return telegram notifier from app state, or None."""
    return getattr(request.app.state, "telegram_notifier", None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/trading/start",
    response_model=TradingStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start the live trading engine",
)
async def start_trading(request: Request) -> TradingStartResponse:
    engine = _get_live_engine(request)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live engine is not available",
        )

    try:
        await engine.start()
        logger.info("live_engine_start_requested")
        add_event(event="trading_start", level="info", message="Live trading engine started")
        return TradingStartResponse(status="ok", message="Live trading engine started")
    except Exception as exc:
        logger.error("live_engine_start_failed", error=str(exc))
        add_event(event="trading_start_failed", level="error", message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start trading engine: {exc}",
        ) from exc


@router.post(
    "/trading/stop",
    response_model=TradingStopResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop the live trading engine",
)
async def stop_trading(request: Request) -> TradingStopResponse:
    engine = _get_live_engine(request)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live engine is not available",
        )

    try:
        await engine.stop()
        logger.info("live_engine_stop_requested")
        add_event(event="trading_stop", level="info", message="Live trading engine stopped")
        return TradingStopResponse(status="ok", message="Live trading engine stopped")
    except Exception as exc:
        logger.error("live_engine_stop_failed", error=str(exc))
        add_event(event="trading_stop_failed", level="error", message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop trading engine: {exc}",
        ) from exc


@router.get(
    "/trading/status",
    response_model=TradingStatusResponse,
    summary="Get per-pair live trading status",
)
async def get_trading_status(request: Request) -> TradingStatusResponse:
    engine = _get_live_engine(request)
    if engine is None:
        return TradingStatusResponse(running=False, pairs=[])

    try:
        engine_status = engine.get_status()
        is_running: bool = getattr(engine, "is_running", False)
        raw_pairs: dict = engine_status.get("pairs", {})

        pairs = [
            PairStatus(
                pair=pair_name,
                state=s.get("status", "unknown"),
                strategy=s.get("strategy_name", ""),
                timeframe=s.get("timeframe"),
                error=s.get("error"),
            )
            for pair_name, s in raw_pairs.items()
        ]
        return TradingStatusResponse(running=is_running, pairs=pairs)
    except Exception as exc:
        logger.error("live_engine_status_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve trading status: {exc}",
        ) from exc


@router.post(
    "/trading/reset-circuit-breaker",
    response_model=CircuitBreakerResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset the circuit breaker",
)
async def reset_circuit_breaker(request: Request) -> CircuitBreakerResetResponse:
    cb = _get_circuit_breaker(request)
    if cb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Circuit breaker is not available",
        )

    try:
        await cb.reset()
        logger.info("circuit_breaker_reset")
        add_event(event="circuit_breaker_reset", level="info", message="Circuit breaker reset")
        return CircuitBreakerResetResponse(status="ok", message="Circuit breaker reset successfully")
    except Exception as exc:
        logger.error("circuit_breaker_reset_failed", error=str(exc))
        add_event(event="circuit_breaker_reset_failed", level="error", message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset circuit breaker: {exc}",
        ) from exc


@router.get(
    "/trading/logs",
    response_model=TradingLogsResponse,
    summary="Get recent runtime trading logs",
)
async def get_trading_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> TradingLogsResponse:
    # Primary source: durable DB logs (survive restarts)
    try:
        result = await db.execute(
            select(RuntimeEvent)
            .order_by(RuntimeEvent.id.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())

        if rows:
            items = [
                TradingLogEvent(
                    id=row.id,
                    timestamp=row.timestamp.isoformat(),
                    level=row.level,
                    event=row.event,
                    pair=row.pair,
                    strategy=row.strategy,
                    timeframe=row.timeframe,
                    message=row.message,
                    details=row.details_json or {},
                )
                for row in reversed(rows)
            ]
            return TradingLogsResponse(items=items)
    except SQLAlchemyError as exc:
        logger.warning("trading_logs_db_read_failed_fallback_memory", error=str(exc))

    # Fallback: in-memory buffer (for early startup edge cases)
    items = [TradingLogEvent(**e) for e in list_events(limit=limit)]
    return TradingLogsResponse(items=items)


@router.post(
    "/trading/telegram/test",
    response_model=TelegramTestResponse,
    summary="Send a Telegram test message",
)
async def test_telegram_notification(request: Request) -> TelegramTestResponse:
    notifier = _get_telegram_notifier(request)
    if notifier is None or not getattr(notifier, "enabled", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram notifier is not enabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
        )

    ok = await notifier.send_text("[OKX BOT] Telegram test message: notifier is working.")
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram API request failed",
        )

    return TelegramTestResponse(status="ok", message="Telegram test message sent")
