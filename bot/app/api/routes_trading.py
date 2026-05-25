"""Trading/runtime API routes for the Funding/OI demo trader."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_events import list_events
from app.core.basis_arbitrage import STRATEGY_NAME as BASIS_ARBITRAGE_STRATEGY_NAME
from app.core.basis_arbitrage import build_basis_arbitrage_rows
from app.core.market_dislocation import build_market_dislocation_rows
from app.db.database import get_db
from app.logging_config import get_logger
from app.models.runtime_event import RuntimeEvent
from app.models.research_market import BasisArbitrageSnapshot, PerpMarketSnapshot

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


class FundingOiDemoStatusResponse(BaseModel):
    running: bool
    stale: bool
    status: str
    strategy_name: str
    mode: str | None = None
    dry_run: bool | None = None
    started_at: str | None = None
    last_loop_at: str | None = None
    latest_event_at: str | None = None
    snapshot_count_seen: int | None = None
    open_position: dict[str, Any] | None = None
    closed_trade_count: int = 0
    processed_event_count: int = 0
    order_error_count: int = 0
    close_error_count: int = 0
    reconciliation_count: int = 0
    reconciliation_error_count: int = 0
    watched_instrument_count: int = 0
    watched_instruments: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


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


class MarketDislocationRowOut(BaseModel):
    inst_id: str
    observed_at: str
    age_seconds: float
    price: float
    lookback_return_pct: float | None
    funding_rate: float | None
    oi_change_pct: float | None
    spread_pct: float
    book_imbalance: float
    trade_imbalance: float
    price_flush_score: float
    funding_heat_score: float
    oi_buildup_score: float
    spread_quality_score: float
    flow_imbalance_score: float
    book_imbalance_score: float
    dislocation_score: float
    candidate_side: str
    readiness: str
    signal_ready: bool
    reason: str


class MarketDislocationResponse(BaseModel):
    strategy_name: str
    generated_at: str
    lookback_seconds: int
    fresh_seconds: int
    item_count: int
    ready_count: int
    items: list[MarketDislocationRowOut]


class BasisArbitrageRowOut(BaseModel):
    inst_id: str
    spot_inst_id: str
    observed_at: str
    age_seconds: float
    perp_mid_price: float
    spot_mid_price: float
    basis_pct: float
    funding_rate: float | None
    funding_8h_pct: float | None
    estimated_daily_funding_pct: float | None
    perp_spread_pct: float
    spot_spread_pct: float
    estimated_round_trip_cost_pct: float
    net_funding_8h_after_cost_pct: float | None
    candidate_side: str
    carry_score: float
    readiness: str
    signal_ready: bool
    reason: str


class BasisArbitrageResponse(BaseModel):
    strategy_name: str
    generated_at: str
    fresh_seconds: int
    item_count: int
    ready_count: int
    items: list[BasisArbitrageRowOut]


def _snapshot_payload(row: PerpMarketSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": row.id,
        "inst_id": row.inst_id,
        "observed_at": row.observed_at,
        "mid_price": row.mid_price,
        "last_price": row.last_price,
        "spread_pct": row.spread_pct,
        "bid_depth_notional": row.bid_depth_notional,
        "ask_depth_notional": row.ask_depth_notional,
        "book_imbalance": row.book_imbalance,
        "reported_buy_notional": row.reported_buy_notional,
        "reported_sell_notional": row.reported_sell_notional,
        "funding_rate": row.funding_rate,
        "open_interest": row.open_interest,
        "open_interest_usd": row.open_interest_usd,
    }


def _basis_snapshot_payload(row: BasisArbitrageSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": row.id,
        "inst_id": row.inst_id,
        "spot_inst_id": row.spot_inst_id,
        "observed_at": row.observed_at,
        "perp_mid_price": row.perp_mid_price,
        "spot_mid_price": row.spot_mid_price,
        "perp_last_price": row.perp_last_price,
        "spot_last_price": row.spot_last_price,
        "perp_spread_pct": row.perp_spread_pct,
        "spot_spread_pct": row.spot_spread_pct,
        "basis_pct": row.basis_pct,
        "funding_rate": row.funding_rate,
        "estimated_daily_funding_pct": row.estimated_daily_funding_pct,
    }


def _get_telegram_notifier(request: Request) -> Any:
    return getattr(request.app.state, "telegram_notifier", None)


def _event_timestamp(row: RuntimeEvent) -> datetime:
    ts = row.timestamp
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _funding_oi_demo_status_from_event(row: RuntimeEvent | None) -> FundingOiDemoStatusResponse:
    if row is None:
        return FundingOiDemoStatusResponse(
            running=False,
            stale=True,
            status="not_started",
            strategy_name="Funding + OI Flush Reversal",
            message="No funding/OI demo trader heartbeat has been recorded.",
        )

    details = row.details_json or {}
    event_at = _event_timestamp(row)
    stale_after_seconds = float(details.get("stale_after_seconds") or 120)
    age_seconds = (datetime.now(timezone.utc) - event_at).total_seconds()
    stale = age_seconds > stale_after_seconds
    raw_status = str(details.get("status") or "unknown")
    running = row.event != "funding_oi_demo_stopped" and raw_status == "running" and not stale
    status_text = "running" if running else ("stale" if stale and row.event != "funding_oi_demo_stopped" else raw_status)

    instruments = details.get("watched_instruments") or []
    if not isinstance(instruments, list):
        instruments = []

    return FundingOiDemoStatusResponse(
        running=running,
        stale=stale,
        status=status_text,
        strategy_name=str(details.get("strategy_name") or row.strategy or "Funding + OI Flush Reversal"),
        mode=details.get("mode"),
        dry_run=details.get("dry_run"),
        started_at=details.get("started_at"),
        last_loop_at=details.get("last_loop_at"),
        latest_event_at=event_at.isoformat(),
        snapshot_count_seen=details.get("snapshot_count_seen"),
        open_position=details.get("open_position"),
        closed_trade_count=int(details.get("closed_trade_count") or 0),
        processed_event_count=int(details.get("processed_event_count") or 0),
        order_error_count=int(details.get("order_error_count") or 0),
        close_error_count=int(details.get("close_error_count") or 0),
        reconciliation_count=int(details.get("reconciliation_count") or 0),
        reconciliation_error_count=int(details.get("reconciliation_error_count") or 0),
        watched_instrument_count=int(details.get("watched_instrument_count") or len(instruments)),
        watched_instruments=[str(item) for item in instruments],
        config=details.get("config") if isinstance(details.get("config"), dict) else {},
        message=row.message,
    )


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
    "/trading/funding-oi-demo/status",
    response_model=FundingOiDemoStatusResponse,
    summary="Get Funding/OI demo trader status",
)
async def get_funding_oi_demo_status(
    db: AsyncSession = Depends(get_db),
) -> FundingOiDemoStatusResponse:
    result = await db.execute(
        select(RuntimeEvent)
        .where(
            RuntimeEvent.event.in_(
                (
                    "funding_oi_demo_started",
                    "funding_oi_demo_status",
                    "funding_oi_demo_stopped",
                )
            )
        )
        .order_by(RuntimeEvent.id.desc())
        .limit(1)
    )
    return _funding_oi_demo_status_from_event(result.scalar_one_or_none())


@router.get(
    "/trading/market-dislocation",
    response_model=MarketDislocationResponse,
    summary="Get watched-market dislocation scores",
)
async def get_market_dislocation(
    limit: int = Query(default=80, ge=1, le=200),
    history_seconds: int = Query(default=1800, ge=300, le=21600),
    lookback_seconds: int = Query(default=300, ge=60, le=3600),
    fresh_seconds: int = Query(default=120, ge=30, le=1800),
    min_abs_move_pct: float = Query(default=0.5, gt=0.0, le=20.0),
    min_abs_funding_rate: float = Query(default=0.00005, gt=0.0, le=0.01),
    min_oi_change_pct: float = Query(default=0.2, gt=0.0, le=100.0),
    max_spread_pct: float = Query(default=0.20, gt=0.0, le=5.0),
    db: AsyncSession = Depends(get_db),
) -> MarketDislocationResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=max(history_seconds, lookback_seconds + fresh_seconds))
    result = await db.execute(
        select(PerpMarketSnapshot)
        .where(PerpMarketSnapshot.observed_at >= cutoff)
        .order_by(PerpMarketSnapshot.inst_id.asc(), PerpMarketSnapshot.observed_at.asc())
    )
    snapshots = [_snapshot_payload(row) for row in result.scalars().all()]
    rows = build_market_dislocation_rows(
        snapshots,
        now=now,
        lookback_seconds=lookback_seconds,
        fresh_seconds=fresh_seconds,
        min_abs_move_pct=min_abs_move_pct,
        min_abs_funding_rate=min_abs_funding_rate,
        min_oi_change_pct=min_oi_change_pct,
        max_spread_pct=max_spread_pct,
    )[:limit]
    items = [
        MarketDislocationRowOut(
            **{
                **asdict(row),
                "observed_at": row.observed_at.isoformat(),
            }
        )
        for row in rows
    ]
    return MarketDislocationResponse(
        strategy_name="Funding + OI Flush Reversal",
        generated_at=now.isoformat(),
        lookback_seconds=lookback_seconds,
        fresh_seconds=fresh_seconds,
        item_count=len(items),
        ready_count=sum(1 for item in items if item.signal_ready),
        items=items,
    )


@router.get(
    "/trading/basis-arbitrage",
    response_model=BasisArbitrageResponse,
    summary="Get spot/perp funding-basis arbitrage scores",
)
async def get_basis_arbitrage(
    limit: int = Query(default=80, ge=1, le=200),
    history_seconds: int = Query(default=1800, ge=60, le=21600),
    fresh_seconds: int = Query(default=180, ge=30, le=1800),
    min_abs_funding_rate: float = Query(default=0.0001, ge=0.0, le=0.01),
    min_abs_basis_pct: float = Query(default=0.02, ge=0.0, le=10.0),
    max_spread_pct: float = Query(default=0.20, gt=0.0, le=5.0),
    taker_fee_pct_per_leg: float = Query(default=0.05, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
) -> BasisArbitrageResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=history_seconds)
    result = await db.execute(
        select(BasisArbitrageSnapshot)
        .where(BasisArbitrageSnapshot.observed_at >= cutoff)
        .order_by(BasisArbitrageSnapshot.inst_id.asc(), BasisArbitrageSnapshot.observed_at.asc())
    )
    snapshots = [_basis_snapshot_payload(row) for row in result.scalars().all()]
    rows = build_basis_arbitrage_rows(
        snapshots,
        now=now,
        fresh_seconds=fresh_seconds,
        min_abs_funding_rate=min_abs_funding_rate,
        min_abs_basis_pct=min_abs_basis_pct,
        max_spread_pct=max_spread_pct,
        taker_fee_pct_per_leg=taker_fee_pct_per_leg,
    )[:limit]
    items = [
        BasisArbitrageRowOut(
            **{
                **asdict(row),
                "observed_at": row.observed_at.isoformat(),
            }
        )
        for row in rows
    ]
    return BasisArbitrageResponse(
        strategy_name=BASIS_ARBITRAGE_STRATEGY_NAME,
        generated_at=now.isoformat(),
        fresh_seconds=fresh_seconds,
        item_count=len(items),
        ready_count=sum(1 for item in items if item.signal_ready),
        items=items,
    )


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
