"""In-memory runtime event buffer for dashboard live logs."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

_MAX_EVENTS = 500
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_lock = Lock()
_seq = 0


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
    """Append an event to the in-memory buffer and return it."""
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

    return payload


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    """Return up to ``limit`` latest events (oldest→newest)."""
    clamped = max(1, min(limit, _MAX_EVENTS))
    with _lock:
        return list(_events)[-clamped:]


def clear_events() -> None:
    """Clear all buffered events."""
    global _seq
    with _lock:
        _events.clear()
        _seq = 0
