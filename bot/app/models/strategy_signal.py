from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class StrategySignal(Base):
    """Append-only research signal snapshot.

    Signals are immutable by convention: downstream research should insert new
    rows for changed feature snapshots instead of mutating historical ones.
    """

    __tablename__ = "strategy_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(nullable=False)
    strategy_name: Mapped[str] = mapped_column(nullable=False)
    pair: Mapped[str] = mapped_column(nullable=False)
    timeframe: Mapped[str] = mapped_column(nullable=False)
    profile_name: Mapped[str] = mapped_column(nullable=False)
    profile_version: Mapped[str] = mapped_column(nullable=False)
    evidence_run_id: Mapped[str] = mapped_column(nullable=False)
    signal_side: Mapped[str] = mapped_column(nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    outcomes: Mapped[list[StrategySignalOutcome]] = relationship(
        back_populates="signal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class StrategySignalOutcome(Base):
    """Append-only offline labeling record for a research signal."""

    __tablename__ = "strategy_signal_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    bars_to_exit: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_reason: Mapped[str] = mapped_column(nullable=False)
    max_adverse_excursion: Mapped[float] = mapped_column(Float, nullable=False)
    max_favorable_excursion: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    signal: Mapped[StrategySignal] = relationship(back_populates="outcomes")
