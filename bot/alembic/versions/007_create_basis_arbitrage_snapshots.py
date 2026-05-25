"""create basis arbitrage snapshots

Revision ID: 007
Revises: 006
Create Date: 2026-05-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "basis_arbitrage_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("inst_id", sa.String(), nullable=False),
        sa.Column("spot_inst_id", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("perp_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spot_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("perp_mid_price", sa.Float(), nullable=False),
        sa.Column("spot_mid_price", sa.Float(), nullable=False),
        sa.Column("perp_last_price", sa.Float(), nullable=False),
        sa.Column("spot_last_price", sa.Float(), nullable=False),
        sa.Column("perp_spread_pct", sa.Float(), nullable=False),
        sa.Column("spot_spread_pct", sa.Float(), nullable=False),
        sa.Column("basis_pct", sa.Float(), nullable=False),
        sa.Column("funding_rate", sa.Float(), nullable=True),
        sa.Column("estimated_daily_funding_pct", sa.Float(), nullable=True),
        sa.Column("data_quality_flags", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("raw_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inst_id", "observed_at", name="uq_basis_arbitrage_snapshot_inst_observed"),
    )
    op.create_index(
        "ix_basis_arbitrage_snapshots_inst_observed",
        "basis_arbitrage_snapshots",
        ["inst_id", "observed_at"],
    )
    op.create_index(
        "ix_basis_arbitrage_snapshots_observed",
        "basis_arbitrage_snapshots",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_basis_arbitrage_snapshots_observed", table_name="basis_arbitrage_snapshots")
    op.drop_index("ix_basis_arbitrage_snapshots_inst_observed", table_name="basis_arbitrage_snapshots")
    op.drop_table("basis_arbitrage_snapshots")
