import uuid
from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair: Mapped[str] = mapped_column(nullable=False)
    timeframe: Mapped[str] = mapped_column(nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[float] = mapped_column(nullable=False)
    high: Mapped[float] = mapped_column(nullable=False)
    low: Mapped[float] = mapped_column(nullable=False)
    close: Mapped[float] = mapped_column(nullable=False)
    volume: Mapped[float] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", "timestamp", name="uq_candle_pair_timeframe_timestamp"),
        Index("ix_candle_pair_timeframe_timestamp", "pair", "timeframe", "timestamp"),
    )
