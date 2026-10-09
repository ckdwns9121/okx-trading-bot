"""Read-only status of the Donchian demo trader (state file written by scripts/run_donchian_trader.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter(prefix="/api/trader", tags=["trader"])


def _age_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


@router.get("/donchian", summary="Donchian demo trader status")
async def donchian_status() -> dict[str, Any]:
    path = Path(settings.DONCHIAN_STATE_FILE)
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "not_started"}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"trader state unreadable: {exc}") from exc

    cfg = st.get("config") or {}
    poll = float(cfg.get("poll_seconds") or 600)
    age = _age_seconds(st.get("last_loop_at"))
    running = age is not None and age <= max(3 * poll, 900)
    trades = st.get("trades") or []
    return {
        "status": "running" if running else "stale",
        "strategy": st.get("strategy"),
        "started_at": st.get("started_at"),
        "last_loop_at": st.get("last_loop_at"),
        "age_seconds": age,
        "config": cfg,
        "sleeves": st.get("sleeves") or {},
        "handled_bar": st.get("handled_bar") or {},
        "pending_orders": len(st.get("pending") or {}),
        "trade_count": len(trades),
        "realized_pnl_usd": sum(float(t.get("realized_pnl_usd") or 0.0) for t in trades),
        "fees_usd": sum(float(t.get("fee_usd") or 0.0) for t in trades),
        "recent_trades": trades[-20:],
        "equity_history": (st.get("equity_history") or [])[-120:],
    }
