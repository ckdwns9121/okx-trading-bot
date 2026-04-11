"""Runtime event utilities.

- Keeps a short in-memory ring buffer for low-latency UI updates.
- Persists events asynchronously to the database for durability.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from app.logging_config import get_logger
from app.models.runtime_event import RuntimeEvent

logger = get_logger(__name__)

_MAX_EVENTS = 500
_MAX_PERSIST_QUEUE = 2000
_MAX_PERSIST_BATCH = 50
_PERSIST_FLUSH_TIMEOUT_SEC = 0.2

_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_lock = Lock()
_seq = 0

_persist_queue: asyncio.Queue[dict[str, Any]] | None = None
_persist_task: asyncio.Task[None] | None = None
_session_factory: Callable[[], Any] | None = None


def add_event(
    *,
    event: str,
    level: str = "info",
    message: str | None = None,
    pair: str | None = None,
    strategy: str | None = None,
    timeframe: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an event to memory and queue it for async DB persistence."""
    global _seq

    payload: dict[str, Any] = {
        "id": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        "pair": pair,
        "strategy": strategy,
        "timeframe": timeframe,
        "message": message,
        "details": details or {},
    }

    with _lock:
        _seq += 1
        payload["id"] = _seq
        _events.append(payload)

    queue = _persist_queue
    if queue is not None:
        try:
            queue.put_nowait(payload.copy())
        except asyncio.QueueFull:
            logger.warning(
                "runtime_event_persist_queue_full",
                dropped_event=event,
                max_queue=_MAX_PERSIST_QUEUE,
            )

    return payload


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    """Return up to ``limit`` latest events from memory (oldest→newest)."""
    clamped = max(1, min(limit, _MAX_EVENTS))
    with _lock:
        return list(_events)[-clamped:]


def clear_events() -> None:
    """Clear in-memory buffered events only."""
    global _seq
    with _lock:
        _events.clear()
        _seq = 0


def configure_persistence(
    *,
    session_factory: Callable[[], Any],
    max_queue_size: int = _MAX_PERSIST_QUEUE,
) -> None:
    """Start background task that persists runtime events to DB."""
    global _persist_queue, _persist_task, _session_factory

    if _persist_task is not None and not _persist_task.done():
        return

    _session_factory = session_factory
    _persist_queue = asyncio.Queue(maxsize=max(100, int(max_queue_size)))
    _persist_task = asyncio.create_task(
        _persist_worker(),
        name="runtime-events-persist-worker",
    )
    logger.info("runtime_event_persistence_enabled", max_queue=max_queue_size)


async def shutdown_persistence() -> None:
    """Stop background DB persistence task."""
    global _persist_queue, _persist_task, _session_factory

    task = _persist_task
    _persist_task = None

    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _persist_queue = None
    _session_factory = None
    logger.info("runtime_event_persistence_stopped")


async def _persist_worker() -> None:
    queue = _persist_queue
    if queue is None:
        return

    try:
        while True:
            payload = await queue.get()
            batch: list[dict[str, Any]] = [payload]

            # Short coalescing window for batch DB inserts under bursty traffic.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _PERSIST_FLUSH_TIMEOUT_SEC
            while len(batch) < _MAX_PERSIST_BATCH:
                timeout = deadline - loop.time()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(queue.get(), timeout=timeout))
                except asyncio.TimeoutError:
                    break

            try:
                await _persist_payloads(batch)
            except Exception as exc:
                logger.warning(
                    "runtime_event_persist_failed",
                    runtime_event=batch[0].get("event") if batch else None,
                    batch_size=len(batch),
                    error=str(exc),
                )
            finally:
                for _ in batch:
                    queue.task_done()
    except asyncio.CancelledError:
        # Best-effort flush of remaining queue entries before fully stopping.
        while queue is not None and not queue.empty():
            batch: list[dict[str, Any]] = []
            try:
                while len(batch) < _MAX_PERSIST_BATCH and not queue.empty():
                    batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                pass

            if not batch:
                break

            try:
                await _persist_payloads(batch)
            except Exception:
                pass
            finally:
                for _ in batch:
                    queue.task_done()
        raise


async def _persist_payloads(payloads: list[dict[str, Any]]) -> None:
    if _session_factory is None:
        return
    if not payloads:
        return

    rows: list[RuntimeEvent] = []
    for payload in payloads:
        ts_raw = payload.get("timestamp")
        timestamp: datetime
        if isinstance(ts_raw, str):
            try:
                timestamp = datetime.fromisoformat(ts_raw)
            except ValueError:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        rows.append(
            RuntimeEvent(
                timestamp=timestamp,
                level=str(payload.get("level") or "info"),
                event=str(payload.get("event") or "event"),
                pair=payload.get("pair"),
                strategy=payload.get("strategy"),
                timeframe=payload.get("timeframe"),
                message=payload.get("message"),
                details_json=(payload.get("details") or {}),
            )
        )

    async with _session_factory() as session:
        session.add_all(rows)
        await session.commit()
