"""CRUD operations for all models using SQLAlchemy async sessions."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models.backtest_run import BacktestRun
from app.models.candle import Candle
from app.models.order import Order
from app.models.position import Position
from app.models.strategy_config import StrategyConfig
from app.models.trade import Trade

logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Candle operations                                                    #
# ------------------------------------------------------------------ #


async def get_candles(
    session: AsyncSession,
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    """Return candles for a pair/timeframe in [start, end], ordered by timestamp asc."""
    result = await session.execute(
        select(Candle)
        .where(
            Candle.pair == pair,
            Candle.timeframe == timeframe,
            Candle.timestamp >= start,
            Candle.timestamp <= end,
        )
        .order_by(Candle.timestamp.asc())
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------ #
# Trade operations                                                     #
# ------------------------------------------------------------------ #


async def get_pnl_summary(
    session: AsyncSession,
    source: str,
    since: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return aggregated PnL stats for the given source (and optional date floor)."""
    stmt = select(
        func.coalesce(func.sum(Trade.pnl), 0.0).label("total_pnl"),
        func.count(Trade.id).label("trade_count"),
    ).where(Trade.source == source, Trade.pnl.isnot(None))
    if since is not None:
        stmt = stmt.where(Trade.exit_time >= since)

    result = await session.execute(stmt)
    row = result.one()
    return {"total_pnl": float(row.total_pnl), "trade_count": int(row.trade_count)}


async def create_trade(session: AsyncSession, data: dict[str, Any]) -> Trade:
    """Insert a new Trade record."""
    trade = Trade(**data)
    session.add(trade)
    await session.flush()
    await session.refresh(trade)
    return trade


# ------------------------------------------------------------------ #
# Order operations                                                     #
# ------------------------------------------------------------------ #


async def get_orders(
    session: AsyncSession,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Order]:
    """Return orders with optional status filter."""
    stmt = select(Order).order_by(Order.created_at.desc())
    if status is not None:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_order(session: AsyncSession, data: dict[str, Any]) -> Order:
    """Insert a new Order record."""
    order = Order(**data)
    session.add(order)
    await session.flush()
    await session.refresh(order)
    return order


async def update_order(
    session: AsyncSession,
    order_id: UUID,
    data: dict[str, Any],
) -> Optional[Order]:
    """Update an order by primary key. Returns the updated Order or None."""
    await session.execute(
        update(Order).where(Order.id == order_id).values(**data)
    )
    await session.flush()
    result = await session.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()


# ------------------------------------------------------------------ #
# Position operations                                                  #
# ------------------------------------------------------------------ #


async def get_positions(session: AsyncSession) -> list[Position]:
    """Return all open positions."""
    result = await session.execute(select(Position))
    return list(result.scalars().all())


async def get_position(session: AsyncSession, pair: str) -> Optional[Position]:
    """Return the position for a pair, or None."""
    result = await session.execute(select(Position).where(Position.pair == pair))
    return result.scalar_one_or_none()


async def create_position(session: AsyncSession, data: dict[str, Any]) -> Position:
    """Insert a new Position record."""
    position = Position(**data)
    session.add(position)
    await session.flush()
    await session.refresh(position)
    return position


async def delete_position(session: AsyncSession, pair: str) -> int:
    """Delete position for a pair. Returns number of rows deleted."""
    result = await session.execute(
        delete(Position).where(Position.pair == pair)
    )
    await session.flush()
    return result.rowcount


async def update_position(
    session: AsyncSession,
    pair: str,
    data: dict[str, Any],
) -> Optional[Position]:
    """Update a position by pair. Returns the updated Position or None."""
    await session.execute(
        update(Position).where(Position.pair == pair).values(**data)
    )
    await session.flush()
    result = await session.execute(select(Position).where(Position.pair == pair))
    return result.scalar_one_or_none()


# ------------------------------------------------------------------ #
# BacktestRun operations                                               #
# ------------------------------------------------------------------ #


async def get_backtest_run(session: AsyncSession, run_id: UUID) -> Optional[BacktestRun]:
    """Return a single backtest run by id."""
    result = await session.execute(
        select(BacktestRun).where(BacktestRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def create_backtest_run(
    session: AsyncSession, data: dict[str, Any]
) -> BacktestRun:
    """Insert a new BacktestRun record."""
    run = BacktestRun(**data)
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


# ------------------------------------------------------------------ #
# StrategyConfig operations                                            #
# ------------------------------------------------------------------ #


async def get_active_configs(session: AsyncSession) -> list[StrategyConfig]:
    """Return all active strategy configs."""
    result = await session.execute(
        select(StrategyConfig).where(StrategyConfig.is_active.is_(True))
    )
    return list(result.scalars().all())


async def upsert_config(
    session: AsyncSession, data: dict[str, Any]
) -> StrategyConfig:
    """Insert or update a StrategyConfig on (strategy_name, pair) conflict."""
    stmt = (
        pg_insert(StrategyConfig)
        .values(**data)
        .on_conflict_do_update(
            constraint="uq_strategy_config_name_pair",
            set_={
                "timeframe": pg_insert(StrategyConfig).excluded.timeframe,
                "parameters_json": pg_insert(StrategyConfig).excluded.parameters_json,
                "leverage": pg_insert(StrategyConfig).excluded.leverage,
                "is_active": pg_insert(StrategyConfig).excluded.is_active,
            },
        )
        .returning(StrategyConfig)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()
