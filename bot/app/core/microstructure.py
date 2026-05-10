from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def evaluate_microstructure_gate(
    *,
    side: str,
    order_notional: float,
    max_spread_pct: float,
    min_visible_depth_notional: float,
    max_market_data_age_seconds: float,
    best_bid: float | None = None,
    best_ask: float | None = None,
    spread_pct: float | None = None,
    visible_depth: float | None = None,
    market_data_timestamp: int | float | datetime | None = None,
    now: datetime | None = None,
    market_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = market_data or {}
    resolved_bid = _coalesce_number(best_bid, snapshot.get("best_bid"), snapshot.get("bid"))
    resolved_ask = _coalesce_number(best_ask, snapshot.get("best_ask"), snapshot.get("ask"))
    resolved_spread_pct = (
        float(spread_pct)
        if spread_pct is not None
        else _spread_pct(resolved_bid, resolved_ask)
    )
    resolved_visible_depth = _resolve_visible_depth(side, visible_depth, snapshot)
    resolved_timestamp = _resolve_timestamp(
        market_data_timestamp,
        snapshot.get("timestamp"),
        snapshot.get("ts"),
        snapshot.get("observed_at"),
    )
    market_data_age_seconds = _market_data_age_seconds(resolved_timestamp, now=now)
    stale = market_data_age_seconds > max_market_data_age_seconds
    expected_price = _expected_price(side, resolved_bid, resolved_ask)
    required_visible_depth = max(
        0.0,
        float(min_visible_depth_notional),
        float(order_notional),
    )

    allow = True
    reason = "ok"
    if expected_price <= 0:
        allow = False
        reason = "missing_market_data"
    elif stale:
        allow = False
        reason = "stale_market_data"
    elif resolved_spread_pct > max_spread_pct:
        allow = False
        reason = "spread_too_wide"
    elif resolved_visible_depth < required_visible_depth:
        allow = False
        reason = "insufficient_visible_depth"

    return {
        "allow": allow,
        "reason": reason,
        "expected_price": expected_price,
        "spread_pct": resolved_spread_pct,
        "visible_depth": resolved_visible_depth,
        "required_visible_depth": required_visible_depth,
        "order_notional": float(order_notional),
        "market_data_age_seconds": market_data_age_seconds,
        "stale": stale,
    }


def should_allow_microstructure_entry(**kwargs: Any) -> tuple[bool, dict[str, Any]]:
    payload = evaluate_microstructure_gate(**kwargs)
    return bool(payload["allow"]), payload


def _resolve_visible_depth(
    side: str,
    explicit_visible_depth: float | None,
    snapshot: Mapping[str, Any],
) -> float:
    if explicit_visible_depth is not None:
        return float(explicit_visible_depth)

    normalized_side = side.strip().lower()
    if normalized_side in {"buy", "long"}:
        return _coalesce_number(
            snapshot.get("ask_depth_notional"),
            snapshot.get("visible_depth"),
        )
    if normalized_side in {"sell", "short"}:
        return _coalesce_number(
            snapshot.get("bid_depth_notional"),
            snapshot.get("visible_depth"),
        )
    return _coalesce_number(snapshot.get("visible_depth"))


def _expected_price(side: str, bid: float, ask: float) -> float:
    normalized_side = side.strip().lower()
    if normalized_side in {"buy", "long"}:
        return ask
    if normalized_side in {"sell", "short"}:
        return bid
    if ask > 0:
        return ask
    return bid


def _spread_pct(bid: float, ask: float) -> float:
    if bid <= 0 or ask <= 0:
        return 0.0
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.0
    return ((ask - bid) / mid) * 100.0


def _market_data_age_seconds(
    market_data_timestamp: datetime | None,
    *,
    now: datetime | None = None,
) -> float:
    if market_data_timestamp is None:
        return float("inf")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    delta = (current - market_data_timestamp).total_seconds()
    return max(0.0, delta)


def _resolve_timestamp(*candidates: Any) -> datetime | None:
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, datetime):
            return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
        try:
            value = int(str(candidate))
        except (TypeError, ValueError):
            continue
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return None


def _coalesce_number(*values: Any) -> float:
    for value in values:
        try:
            if value is None:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0
