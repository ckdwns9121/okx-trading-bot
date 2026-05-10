from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger

logger = get_logger(__name__)

# OKX returns timestamps as milliseconds since epoch
_MS_PER_SECOND = 1000


class CandleClient(Protocol):
    async def get_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100,
        after: str | None = None,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


def _ms_to_dt(ms: str | int) -> datetime:
    """Convert a millisecond timestamp (string or int) to a naive UTC datetime."""
    return datetime.utcfromtimestamp(int(ms) / _MS_PER_SECOND)


class DataCollector:
    """Fetches historical candles from OKX and persists them to the database."""

    def __init__(self, okx_client: CandleClient, db_session: AsyncSession) -> None:
        self._client = okx_client
        self._session = db_session

    async def fetch_historical_candles(
        self,
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> int:
        """Paginate through the OKX candle history and upsert to the DB.

        OKX pagination:
          - ``after``  → returns candles *before* that timestamp (older)
          - ``before`` → returns candles *after* that timestamp (newer)
        We walk backwards from end_date until we reach start_date.

        Returns the total number of candles upserted.
        """
        start_ms = int(start_date.timestamp() * _MS_PER_SECOND)
        end_ms = int(end_date.timestamp() * _MS_PER_SECOND)

        total_saved = 0
        # cursor starts just after end_date so the first page includes it
        cursor_after: str | None = str(end_ms + 1)

        logger.info(
            "historical_fetch_start",
            pair=pair,
            timeframe=timeframe,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        while True:
            candles: list[dict[str, Any]] = await self._client.get_candles(
                pair=pair,
                timeframe=timeframe,
                limit=100,
                after=cursor_after,
            )

            if not candles:
                logger.debug("no_more_candles", pair=pair, cursor=cursor_after)
                break

            # Filter to the requested window and build upsert rows
            rows_to_upsert: list[dict[str, Any]] = []

            for c in candles:
                ts_ms = int(c["timestamp"])
                if ts_ms < start_ms:
                    # Past the start boundary; stop after this batch
                    continue
                if ts_ms > end_ms:
                    continue
                rows_to_upsert.append(
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        "timestamp": _ms_to_dt(ts_ms),
                        "open": c["open"],
                        "high": c["high"],
                        "low": c["low"],
                        "close": c["close"],
                        "volume": c["volume"],
                    }
                )
            if rows_to_upsert:
                saved = await self._upsert_candles(rows_to_upsert)
                total_saved += saved
                logger.debug(
                    "batch_upserted",
                    pair=pair,
                    count=saved,
                    total=total_saved,
                )

            # Determine whether we have reached the start of the window
            # OKX returns newest-first; the last element in the list is oldest.
            oldest_in_page = int(candles[-1]["timestamp"])
            if oldest_in_page <= start_ms:
                logger.debug("reached_start_boundary", pair=pair)
                break

            # Advance cursor to the oldest timestamp in this page so the next
            # request returns candles strictly older than it.
            cursor_after = str(oldest_in_page)

            # If this batch had fewer than 100 items there's nothing older.
            if len(candles) < 100:
                break

        logger.info(
            "historical_fetch_complete",
            pair=pair,
            timeframe=timeframe,
            total_candles=total_saved,
        )
        return total_saved

    async def _upsert_candles(self, rows: list[dict[str, Any]]) -> int:
        """Bulk upsert candles using ON CONFLICT DO UPDATE."""
        if not rows:
            return 0

        stmt = text(
            """
            INSERT INTO candles (pair, timeframe, timestamp, open, high, low, close, volume)
            VALUES (:pair, :timeframe, :timestamp, :open, :high, :low, :close, :volume)
            ON CONFLICT (pair, timeframe, timestamp)
            DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
            """
        )

        for row in rows:
            await self._session.execute(stmt, row)

        await self._session.flush()
        return len(rows)
