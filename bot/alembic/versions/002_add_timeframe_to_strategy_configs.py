"""add timeframe to strategy_configs

Revision ID: 002
Revises: 001
Create Date: 2026-04-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_configs",
        sa.Column("timeframe", sa.String(), nullable=False, server_default="1m"),
    )


def downgrade() -> None:
    op.drop_column("strategy_configs", "timeframe")
