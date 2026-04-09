"""create runtime_events table

Revision ID: 003
Revises: 002
Create Date: 2026-04-07

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=True),
        sa.Column("strategy", sa.String(), nullable=True),
        sa.Column("timeframe", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_runtime_events_timestamp", "runtime_events", ["timestamp"])
    op.create_index("ix_runtime_events_event_pair", "runtime_events", ["event", "pair"])


def downgrade() -> None:
    op.drop_index("ix_runtime_events_event_pair", table_name="runtime_events")
    op.drop_index("ix_runtime_events_timestamp", table_name="runtime_events")
    op.drop_table("runtime_events")
