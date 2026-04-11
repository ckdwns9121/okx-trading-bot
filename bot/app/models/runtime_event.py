from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    level: Mapped[str] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(nullable=False)
    pair: Mapped[str | None] = mapped_column(nullable=True)
    strategy: Mapped[str | None] = mapped_column(nullable=True)
    timeframe: Mapped[str | None] = mapped_column(nullable=True)
    message: Mapped[str | None] = mapped_column(nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
