"""Circuit breaker: halt trading when daily loss limit is breached."""

from datetime import datetime, timezone

from app.db.repository import get_pnl_summary
from app.logging_config import get_logger

logger = get_logger(__name__)


class CircuitBreaker:
    """Monitors realized daily PnL and trips when the loss limit is exceeded.

    Once tripped, all order placement is blocked until manually reset.
    """

    def __init__(self, session_factory, max_daily_loss: float) -> None:
        self._session_factory = session_factory
        self._max_daily_loss = abs(max_daily_loss)
        self._tripped: bool = False

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    async def check(self) -> bool:
        """Return True if trading is allowed, False if the circuit is tripped."""
        if self._tripped:
            logger.warning(
                "circuit_breaker_already_tripped",
                max_daily_loss=self._max_daily_loss,
            )
            return False

        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            async with self._session_factory() as session:
                summary = await get_pnl_summary(
                    session, source="live", since=today_start
                )
        except Exception as exc:
            logger.error("circuit_breaker_check_error", error=str(exc))
            return True

        daily_pnl: float = summary["total_pnl"]
        loss = -daily_pnl

        if loss >= self._max_daily_loss:
            await self.trip()
            return False

        logger.debug(
            "circuit_breaker_ok",
            daily_pnl=daily_pnl,
            max_daily_loss=self._max_daily_loss,
        )
        return True

    async def trip(self) -> None:
        self._tripped = True
        logger.critical(
            "circuit_breaker_tripped",
            max_daily_loss=self._max_daily_loss,
            message="Daily loss limit exceeded — all order placement blocked",
        )

    def reset(self) -> None:
        self._tripped = False
        logger.info("circuit_breaker_reset", max_daily_loss=self._max_daily_loss)
