"""create strategy_signals tables

Revision ID: 004
Revises: 003
Create Date: 2026-05-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("profile_name", sa.String(), nullable=False),
        sa.Column("profile_version", sa.String(), nullable=False),
        sa.Column("evidence_run_id", sa.String(), nullable=False),
        sa.Column("signal_side", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_strategy_signals_lookup",
        "strategy_signals",
        ["strategy_name", "pair", "timeframe", "timestamp"],
    )
    op.create_index(
        "ix_strategy_signals_run_profile",
        "strategy_signals",
        ["evidence_run_id", "profile_name", "profile_version"],
    )

    op.create_table(
        "strategy_signal_outcomes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "signal_id",
            UUID(as_uuid=True),
            sa.ForeignKey("strategy_signals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("outcome_pnl", sa.Float(), nullable=False),
        sa.Column("bars_to_exit", sa.Integer(), nullable=False),
        sa.Column("exit_reason", sa.String(), nullable=False),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=False),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_strategy_signal_outcomes_signal_created",
        "strategy_signal_outcomes",
        ["signal_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_signal_outcomes_signal_created", table_name="strategy_signal_outcomes")
    op.drop_table("strategy_signal_outcomes")
    op.drop_index("ix_strategy_signals_run_profile", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_lookup", table_name="strategy_signals")
    op.drop_table("strategy_signals")
