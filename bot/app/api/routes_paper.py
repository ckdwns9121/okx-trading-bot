"""Paper trading status API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter(prefix="/api/paper", tags=["paper"])


@router.get("/trend-following", summary="Trend-following paper trader status")
async def get_trend_following_status() -> dict[str, Any]:
    path = Path(settings.PAPER_TREND_STATE_FILE)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"running": False, "message": "paper trader has not run yet"}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"paper state unreadable: {exc}") from exc

    trades = state.get("trades", [])
    equity_history = state.get("equity_history", [])
    return {
        "running": True,
        "strategy": state.get("strategy"),
        "started_at": state.get("started_at"),
        "last_loop_at": state.get("last_loop_at"),
        "book": state.get("book", {}),
        "trade_count": len(trades),
        "recent_trades": trades[-20:],
        "equity_history": equity_history[-500:],
    }
