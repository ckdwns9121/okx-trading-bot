"""drop legacy candle-strategy tables

Revision ID: 006
Revises: 005
Create Date: 2026-05-23

"""

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE trades DROP COLUMN IF EXISTS backtest_run_id CASCADE")
    op.execute("DROP TABLE IF EXISTS strategy_signal_outcomes CASCADE")
    op.execute("DROP TABLE IF EXISTS strategy_signals CASCADE")
    op.execute("DROP TABLE IF EXISTS strategy_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS backtest_runs CASCADE")


def downgrade() -> None:
    # Intentionally not recreated: these tables belonged to the removed
    # legacy candle-strategy/backtest platform.
    pass
