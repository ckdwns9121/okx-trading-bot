import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(nullable=False)
    pair: Mapped[str] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(nullable=False)
    entry_price: Mapped[float] = mapped_column(nullable=False)
    exit_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    quantity: Mapped[float] = mapped_column(nullable=False)
    leverage: Mapped[int] = mapped_column(nullable=False)
    pnl: Mapped[Optional[float]] = mapped_column(nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    fee: Mapped[float] = mapped_column(nullable=False, default=0.0)
    entry_time: Mapped[datetime] = mapped_column(nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)
    entry_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )
    exit_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )
