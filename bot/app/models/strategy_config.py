import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(nullable=False)
    pair: Mapped[str] = mapped_column(nullable=False)
    timeframe: Mapped[str] = mapped_column(nullable=False, default="1m")
    parameters_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    leverage: Mapped[int] = mapped_column(nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("strategy_name", "pair", name="uq_strategy_config_name_pair"),
    )
