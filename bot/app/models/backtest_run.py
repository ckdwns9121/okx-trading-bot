import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    strategy_name: Mapped[str] = mapped_column(nullable=False)
    pair: Mapped[str] = mapped_column(nullable=False)
    timeframe: Mapped[str] = mapped_column(nullable=False)
    start_date: Mapped[datetime] = mapped_column(nullable=False)
    end_date: Mapped[datetime] = mapped_column(nullable=False)
    initial_balance: Mapped[float] = mapped_column(nullable=False)
    leverage: Mapped[int] = mapped_column(nullable=False)
    fee_rate: Mapped[float] = mapped_column(nullable=False)
    slippage_pct: Mapped[float] = mapped_column(nullable=False)
    total_pnl: Mapped[Optional[float]] = mapped_column(nullable=True)
    win_rate: Mapped[Optional[float]] = mapped_column(nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(nullable=True)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    trade_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    parameters_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
