import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair: Mapped[str] = mapped_column(nullable=False, unique=True)
    direction: Mapped[str] = mapped_column(nullable=False)
    entry_price: Mapped[float] = mapped_column(nullable=False)
    quantity: Mapped[float] = mapped_column(nullable=False)
    leverage: Mapped[int] = mapped_column(nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(nullable=False, default=0.0)
    exchange_position_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    opened_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
