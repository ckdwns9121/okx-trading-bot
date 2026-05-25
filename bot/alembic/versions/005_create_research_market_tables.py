"""create research market tables

Revision ID: 005
Revises: 004
Create Date: 2026-05-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "perp_market_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("inst_id", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("book_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trades_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oi_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mid_price", sa.Float(), nullable=False),
        sa.Column("last_price", sa.Float(), nullable=False),
        sa.Column("spread_pct", sa.Float(), nullable=False),
        sa.Column("bid_depth_notional", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ask_depth_notional", sa.Float(), nullable=False, server_default="0"),
        sa.Column("book_imbalance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reported_buy_notional", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reported_sell_notional", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reported_buy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reported_sell_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("funding_rate", sa.Float(), nullable=True),
        sa.Column("premium", sa.Float(), nullable=True),
        sa.Column("open_interest", sa.Float(), nullable=True),
        sa.Column("open_interest_usd", sa.Float(), nullable=True),
        sa.Column("data_quality_flags", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("raw_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inst_id", "observed_at", name="uq_perp_market_snapshot_inst_observed"),
    )
    op.create_index(
        "ix_perp_market_snapshots_inst_observed",
        "perp_market_snapshots",
        ["inst_id", "observed_at"],
    )

    op.create_table(
        "research_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("inst_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_side", sa.String(), nullable=False),
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey("perp_market_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("crowding_score", sa.Float(), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_research_events_inst_time", "research_events", ["inst_id", "occurred_at"])
    op.create_index("ix_research_events_type_time", "research_events", ["event_type", "occurred_at"])

    op.create_table(
        "research_event_outcomes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("research_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("horizon_seconds", sa.Integer(), nullable=False),
        sa.Column("future_return_pct", sa.Float(), nullable=False),
        sa.Column("cost_adjusted_edge_pct", sa.Float(), nullable=False),
        sa.Column("max_adverse_excursion_pct", sa.Float(), nullable=False),
        sa.Column("max_favorable_excursion_pct", sa.Float(), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("outcome_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "horizon_seconds", name="uq_research_event_outcome_horizon"),
    )
    op.create_index(
        "ix_research_event_outcomes_event_horizon",
        "research_event_outcomes",
        ["event_id", "horizon_seconds"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_event_outcomes_event_horizon", table_name="research_event_outcomes")
    op.drop_table("research_event_outcomes")
    op.drop_index("ix_research_events_type_time", table_name="research_events")
    op.drop_index("ix_research_events_inst_time", table_name="research_events")
    op.drop_table("research_events")
    op.drop_index("ix_perp_market_snapshots_inst_observed", table_name="perp_market_snapshots")
    op.drop_table("perp_market_snapshots")
