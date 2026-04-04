"""initial

Revision ID: 001
Revises:
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Candles
    op.create_table(
        "candles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.UniqueConstraint("pair", "timeframe", "timestamp", name="uq_candle"),
    )
    op.create_index("ix_candle_pair_tf_ts", "candles", ["pair", "timeframe", "timestamp"])

    # Orders
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("exchange_order_id", sa.String(), nullable=True),
        sa.Column("cl_ord_id", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Backtest runs
    op.create_table(
        "backtest_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=False),
        sa.Column("initial_balance", sa.Float(), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("fee_rate", sa.Float(), nullable=False),
        sa.Column("slippage_pct", sa.Float(), nullable=False),
        sa.Column("total_pnl", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("parameters_json", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Trades
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("backtest_run_id", UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id"), nullable=True),
        sa.Column("entry_order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("exit_order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
    )

    # Positions
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pair", sa.String(), nullable=False, unique=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("exchange_position_id", sa.String(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Strategy configs
    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("parameters_json", JSON(), nullable=True),
        sa.Column("leverage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("strategy_name", "pair", name="uq_strategy_config_name_pair"),
    )


def downgrade() -> None:
    op.drop_table("strategy_configs")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("backtest_runs")
    op.drop_table("orders")
    op.drop_index("ix_candle_pair_tf_ts", "candles")
    op.drop_table("candles")
