"""Paper / demo trader status API (read-only views over their state files)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter(prefix="/api/paper", tags=["paper"])

# A demo loop that has not reported for this long is considered stale even
# when its config says it should poll more often (clock skew, long OKX stalls).
DEMO_STALE_FLOOR_SECONDS = 15 * 60


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.get("/demo-trader", summary="OKX demo trader status")
async def get_demo_trader_status() -> dict[str, Any]:
    path = Path(settings.DEMO_TREND_STATE_FILE)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"running": False, "status": "not_started", "message": "demo trader has not run yet"}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"demo state unreadable: {exc}") from exc

    config = state.get("config") if isinstance(state.get("config"), dict) else None
    processed = state.get("processed_candle_ts") or {}
    pairs = list(config["pairs"]) if config and config.get("pairs") else sorted(processed)

    last_loop = _parse_iso(state.get("last_loop_at"))
    age_seconds: float | None = None
    if last_loop is not None:
        age_seconds = max(0.0, (datetime.now(timezone.utc) - last_loop).total_seconds())
    poll = float(config.get("poll_seconds", 3600)) if config else 3600.0
    stale_after = max(DEMO_STALE_FLOOR_SECONDS, poll * 2)
    running = age_seconds is not None and age_seconds <= stale_after

    trades = [row for row in state.get("trades", []) if isinstance(row, dict)]
    realized = sum(float(row.get("realized_pnl_usd") or 0.0) for row in trades)
    fees = sum(float(row.get("fee_usd") or 0.0) for row in trades)
    positions = {
        pair: row
        for pair, row in (state.get("positions") or {}).items()
        if isinstance(row, dict) and float(row.get("contracts") or 0.0) > 0.0
    }

    return {
        "running": running,
        "status": "running" if running else ("stale" if last_loop else "not_started"),
        "strategy": state.get("strategy"),
        "started_at": state.get("started_at"),
        "last_loop_at": state.get("last_loop_at"),
        "age_seconds": age_seconds,
        "stale_after_seconds": stale_after,
        "config": config,
        "pairs": pairs,
        "processed_candle_ts": processed,
        "positions": positions,
        "trade_count": len(trades),
        "realized_pnl_usd": realized,
        "fees_paid_usd": fees,
        "recent_trades": trades[-20:],
    }


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
