"""Circuit breaker: halt trading when risk limits are breached."""

from datetime import datetime, timezone

from app.db.repository import get_pnl_summary
from app.logging_config import get_logger

logger = get_logger(__name__)


class CircuitBreaker:
    """Monitors realized PnL and trips when configured loss limits are exceeded.

    Once tripped, all order placement is blocked until manually reset.
    """

    def __init__(
        self,
        session_factory,
        max_daily_loss: float,
        max_monthly_loss: float,
    ) -> None:
        self._session_factory = session_factory
        self._max_daily_loss = abs(max_daily_loss)
        self._max_monthly_loss = abs(max_monthly_loss)
        self._tripped: bool = False
        self._trip_reason: str | None = None

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def trip_reason(self) -> str | None:
        return self._trip_reason

    async def check(self) -> bool:
        """Return True if trading is allowed, False if the circuit is tripped."""
        if self._tripped:
            logger.warning(
                "circuit_breaker_already_tripped",
                max_daily_loss=self._max_daily_loss,
                max_monthly_loss=self._max_monthly_loss,
                reason=self._trip_reason,
            )
            return False

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        try:
            async with self._session_factory() as session:
                daily_summary = await get_pnl_summary(
                    session, source="live", since=today_start
                )
                monthly_summary = await get_pnl_summary(
                    session, source="live", since=month_start
                )
        except Exception as exc:
            logger.error("circuit_breaker_check_error", error=str(exc))
            return True

        daily_pnl: float = daily_summary["total_pnl"]
        monthly_pnl: float = monthly_summary["total_pnl"]
        daily_loss = -daily_pnl
        monthly_loss = -monthly_pnl

        if daily_loss >= self._max_daily_loss:
            await self.trip("daily_loss_limit")
            return False

        if monthly_loss >= self._max_monthly_loss:
            await self.trip("monthly_loss_limit")
            return False

        logger.debug(
            "circuit_breaker_ok",
            daily_pnl=daily_pnl,
            monthly_pnl=monthly_pnl,
            max_daily_loss=self._max_daily_loss,
            max_monthly_loss=self._max_monthly_loss,
        )
        return True

    async def trip(self, reason: str = "manual_trip") -> None:
        self._tripped = True
        self._trip_reason = reason
        logger.critical(
            "circuit_breaker_tripped",
            max_daily_loss=self._max_daily_loss,
            max_monthly_loss=self._max_monthly_loss,
            reason=reason,
            message="Risk loss limit exceeded — all order placement blocked",
        )

    async def reset(self) -> None:
        self._tripped = False
        self._trip_reason = None
        logger.info(
            "circuit_breaker_reset",
            max_daily_loss=self._max_daily_loss,
            max_monthly_loss=self._max_monthly_loss,
        )
