from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PerpMarketSnapshot(Base):
    """Append-only normalized evidence for perpetual market research."""

    __tablename__ = "perp_market_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    inst_id: Mapped[str] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ticker_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    book_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trades_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    funding_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    oi_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mid_price: Mapped[float] = mapped_column(Float, nullable=False)
    last_price: Mapped[float] = mapped_column(Float, nullable=False)
    spread_pct: Mapped[float] = mapped_column(Float, nullable=False)
    bid_depth_notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ask_depth_notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    book_imbalance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reported_buy_notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reported_sell_notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reported_buy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_sell_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality_flags: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("inst_id", "observed_at", name="uq_perp_market_snapshot_inst_observed"),
        Index("ix_perp_market_snapshots_inst_observed", "inst_id", "observed_at"),
    )


class BasisArbitrageSnapshot(Base):
    """Spot/perpetual evidence for market-neutral funding/basis research."""

    __tablename__ = "basis_arbitrage_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    inst_id: Mapped[str] = mapped_column(nullable=False)
    spot_inst_id: Mapped[str] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    perp_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    spot_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    funding_source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    perp_mid_price: Mapped[float] = mapped_column(Float, nullable=False)
    spot_mid_price: Mapped[float] = mapped_column(Float, nullable=False)
    perp_last_price: Mapped[float] = mapped_column(Float, nullable=False)
    spot_last_price: Mapped[float] = mapped_column(Float, nullable=False)
    perp_spread_pct: Mapped[float] = mapped_column(Float, nullable=False)
    spot_spread_pct: Mapped[float] = mapped_column(Float, nullable=False)
    basis_pct: Mapped[float] = mapped_column(Float, nullable=False)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_daily_funding_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality_flags: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("inst_id", "observed_at", name="uq_basis_arbitrage_snapshot_inst_observed"),
        Index("ix_basis_arbitrage_snapshots_inst_observed", "inst_id", "observed_at"),
        Index("ix_basis_arbitrage_snapshots_observed", "observed_at"),
    )


class ResearchEvent(Base):
    """Research-only candidate event derived from stored market snapshots."""

    __tablename__ = "research_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(nullable=False)
    inst_id: Mapped[str] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candidate_side: Mapped[str] = mapped_column(nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("perp_market_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    crowding_score: Mapped[float] = mapped_column(Float, nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    outcomes: Mapped[list[ResearchEventOutcome]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_research_events_inst_time", "inst_id", "occurred_at"),
        Index("ix_research_events_type_time", "event_type", "occurred_at"),
    )


class ResearchEventOutcome(Base):
    """Offline forward-outcome label for a research event."""

    __tablename__ = "research_event_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    future_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    cost_adjusted_edge_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_adverse_excursion_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_favorable_excursion_pct: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    event: Mapped[ResearchEvent] = relationship(back_populates="outcomes")

    __table_args__ = (
        UniqueConstraint("event_id", "horizon_seconds", name="uq_research_event_outcome_horizon"),
        Index("ix_research_event_outcomes_event_horizon", "event_id", "horizon_seconds"),
    )
