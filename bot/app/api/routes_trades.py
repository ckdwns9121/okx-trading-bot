"""Trade / order / PnL / position query routes.

GET /api/trades    — query trades with optional filters
GET /api/pnl       — realized PnL summary for live trades
GET /api/orders    — list orders
GET /api/positions — list open positions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.logging_config import get_logger
from app.models.order import Order
from app.models.position import Position
from app.models.trade import Trade

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["trades"])


def _normalize_direction(direction: str | None) -> str:
    value = (direction or "").strip().lower()
    if value in ("buy", "long"):
        return "long"
    if value in ("sell", "short"):
        return "short"
    return value or "unknown"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TradeOut(BaseModel):
    id: int
    strategy_name: str
    pair: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    leverage: int
    pnl: Optional[float]
    pnl_pct: Optional[float]
    fee: float
    entry_time: datetime
    exit_time: Optional[datetime]
    status: str
    source: str

    model_config = {"from_attributes": True}


class PnLResponse(BaseModel):
    realized_pnl: float
    win_rate: float
    trade_count: int
    today_pnl: float


class OrderOut(BaseModel):
    id: uuid.UUID
    pair: str
    side: str
    order_type: str
    price: Optional[float]
    quantity: float
    leverage: int
    status: str
    exchange_order_id: Optional[str]
    cl_ord_id: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    id: int
    pair: str
    direction: str
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float
    exchange_position_id: Optional[str]
    opened_at: datetime

    model_config = {"from_attributes": True}


class AccountBalanceResponse(BaseModel):
    total_equity: float
    usdt_equity: float
    usdt_available: float
    updated_at_ms: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/trades",
    response_model=list[TradeOut],
    summary="Query trades with optional filters",
)
async def list_trades(
    source: Optional[Literal["live", "paper", "demo"]] = Query(default=None),
    pair: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[TradeOut]:
    stmt = select(Trade).order_by(Trade.entry_time.desc())

    if source is not None:
        stmt = stmt.where(Trade.source == source)
    if pair is not None:
        stmt = stmt.where(Trade.pair == pair)
    if strategy is not None:
        stmt = stmt.where(Trade.strategy_name == strategy)

    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    trades = result.scalars().all()

    rows: list[TradeOut] = []
    for trade in trades:
        item = TradeOut.model_validate(trade)
        strategy_name = item.strategy_name
        item.direction = _normalize_direction(item.direction)
        item.strategy_name = strategy_name or "unknown"
        rows.append(item)
    return rows


@router.get(
    "/pnl",
    response_model=PnLResponse,
    summary="Realized PnL summary for live trades",
)
async def get_pnl(
    source: Literal["live", "paper", "demo"] = Query(default="live"),
    db: AsyncSession = Depends(get_db),
) -> PnLResponse:
    # Only consider closed trades (status == "closed") with non-null pnl.
    base_stmt = (
        select(Trade)
        .where(Trade.source == source)
        .where(Trade.status == "closed")
        .where(Trade.pnl.is_not(None))
    )

    result = await db.execute(base_stmt)
    trades = result.scalars().all()

    if not trades:
        return PnLResponse(realized_pnl=0.0, win_rate=0.0, trade_count=0, today_pnl=0.0)

    total_pnl = sum(t.pnl for t in trades if t.pnl is not None)
    wins = sum(1 for t in trades if t.pnl is not None and t.pnl > 0)
    trade_count = len(trades)
    win_rate = wins / trade_count if trade_count else 0.0

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_pnl = sum(
        t.pnl
        for t in trades
        if t.pnl is not None
        and t.exit_time is not None
        and t.exit_time.replace(tzinfo=timezone.utc) >= today_start
    )

    return PnLResponse(
        realized_pnl=total_pnl,
        win_rate=win_rate,
        trade_count=trade_count,
        today_pnl=today_pnl,
    )


@router.get(
    "/orders",
    response_model=list[OrderOut],
    summary="List orders",
)
async def list_orders(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[OrderOut]:
    stmt = (
        select(Order)
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [OrderOut.model_validate(o) for o in orders]


@router.get(
    "/positions",
    response_model=list[PositionOut],
    summary="List all open positions",
)
async def list_positions(
    db: AsyncSession = Depends(get_db),
) -> list[PositionOut]:
    result = await db.execute(select(Position).order_by(Position.opened_at.desc()))
    positions = result.scalars().all()
    return [
        PositionOut.model_validate(p).model_copy(update={"direction": _normalize_direction(p.direction)})
        for p in positions
    ]


@router.get(
    "/account/balance",
    response_model=AccountBalanceResponse,
    summary="Get OKX account balance snapshot",
)
async def get_account_balance(request: Request) -> AccountBalanceResponse:
    okx_client = getattr(request.app.state, "okx_client", None)
    if okx_client is None:
        raise HTTPException(status_code=503, detail="OKX client not available")

    try:
        raw = await okx_client.get_account_balance()
    except Exception as exc:
        logger.warning("account_balance_fetch_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to fetch account balance: {exc}") from exc

    row = (raw.get("data") or [{}])[0]
    details = row.get("details") or []
    usdt = next((d for d in details if d.get("ccy") == "USDT"), {})

    def _to_float(v: object) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    return AccountBalanceResponse(
        total_equity=_to_float(row.get("totalEq")),
        usdt_equity=_to_float(usdt.get("eq")),
        usdt_available=_to_float(usdt.get("availEq") or usdt.get("availBal")),
        updated_at_ms=row.get("uTime"),
    )
