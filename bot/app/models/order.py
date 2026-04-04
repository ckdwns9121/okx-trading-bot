import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pair: Mapped[str] = mapped_column(nullable=False)
    side: Mapped[str] = mapped_column(nullable=False)
    order_type: Mapped[str] = mapped_column(nullable=False)
    price: Mapped[Optional[float]] = mapped_column(nullable=True)
    quantity: Mapped[float] = mapped_column(nullable=False)
    leverage: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    exchange_order_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    cl_ord_id: Mapped[str] = mapped_column(nullable=False, default=lambda: uuid.uuid4().hex)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )
