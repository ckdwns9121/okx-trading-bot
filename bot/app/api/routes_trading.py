"""Runtime API routes: trading logs, health check, and Telegram test."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_events import list_events
from app.db.database import get_db
from app.logging_config import get_logger
from app.models.runtime_event import RuntimeEvent

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["trading"])


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


class TradingTasksStatus(BaseModel):
    active: int = 0
    failed: int = 0
    stopped: int = 0


class OKXApiStatus(BaseModel):
    status: str
    mode: str


class HealthResponse(BaseModel):
    db: str
    okx_api: OKXApiStatus
    trading_tasks: TradingTasksStatus = Field(default_factory=TradingTasksStatus)
    circuit_breaker: str = "removed"


def _get_telegram_notifier(request: Request) -> Any:
    return getattr(request.app.state, "telegram_notifier", None)


@router.get(
    "/trading/logs",
    response_model=TradingLogsResponse,
    summary="Get recent runtime trading logs",
)
async def get_trading_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> TradingLogsResponse:
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

    items = [TradingLogEvent(**e) for e in list_events(limit=limit)]
    return TradingLogsResponse(items=items)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Runtime health check",
)
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    from app.config import settings

    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health_check_db_failed", error=str(exc))
        db_status = "error"

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

    return HealthResponse(
        db=db_status,
        okx_api=OKXApiStatus(status=okx_api_status, mode=settings.OKX_MODE),
    )


@router.post(
    "/trading/telegram/test",
    response_model=TelegramTestResponse,
    summary="Send a Telegram test message",
)
async def test_telegram_notification(request: Request) -> TelegramTestResponse:
    notifier = _get_telegram_notifier(request)
    if notifier is None or not getattr(notifier, "enabled", False):
        raise HTTPException(
            status_code=503,
            detail="Telegram notifier is not enabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
        )

    ok = await notifier.send_text("[OKX BOT] Telegram test message: notifier is working.")
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram API request failed")

    return TelegramTestResponse(status="ok", message="Telegram test message sent")
