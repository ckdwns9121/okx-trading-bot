from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class MarketDislocationRow:
    inst_id: str
    observed_at: datetime
    age_seconds: float
    price: float
    lookback_return_pct: float | None
    funding_rate: float | None
    oi_change_pct: float | None
    spread_pct: float
    book_imbalance: float
    trade_imbalance: float
    price_flush_score: float
    funding_heat_score: float
    oi_buildup_score: float
    spread_quality_score: float
    flow_imbalance_score: float
    book_imbalance_score: float
    dislocation_score: float
    candidate_side: str
    readiness: str
    signal_ready: bool
    reason: str


def build_market_dislocation_rows(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    lookback_seconds: int = 300,
    fresh_seconds: int = 120,
    min_abs_move_pct: float = 0.5,
    min_abs_funding_rate: float = 0.00005,
    min_oi_change_pct: float = 0.2,
    max_spread_pct: float = 0.20,
) -> list[MarketDislocationRow]:
    if lookback_seconds <= 0:
        raise ValueError("lookback_seconds must be positive")
    if fresh_seconds <= 0:
        raise ValueError("fresh_seconds must be positive")
    if min_abs_move_pct <= 0.0:
        raise ValueError("min_abs_move_pct must be positive")
    if min_abs_funding_rate <= 0.0:
        raise ValueError("min_abs_funding_rate must be positive")
    if min_oi_change_pct <= 0.0:
        raise ValueError("min_oi_change_pct must be positive")
    if max_spread_pct <= 0.0:
        raise ValueError("max_spread_pct must be positive")

    current_time = _ensure_aware(now or datetime.now(timezone.utc))
    rows: list[MarketDislocationRow] = []
    for inst_id, ordered in _snapshots_by_instrument(snapshots).items():
        latest = ordered[-1]
        observed_at = _ensure_aware(latest["observed_at"])
        reference = _reference_snapshot(ordered, observed_at, lookback_seconds)
        price = _snapshot_price(latest)
        reference_price = _snapshot_price(reference) if reference else 0.0
        current_oi = _snapshot_oi(latest)
        reference_oi = _snapshot_oi(reference) if reference else 0.0
        funding_rate = _optional_float(latest.get("funding_rate"))

        lookback_return_pct = (
            ((price / reference_price) - 1.0) * 100.0
            if price > 0.0 and reference_price > 0.0
            else None
        )
        oi_change_pct = (
            ((current_oi / reference_oi) - 1.0) * 100.0
            if current_oi > 0.0 and reference_oi > 0.0
            else None
        )
        spread_pct = float(latest.get("spread_pct") or 0.0)
        book = float(latest.get("book_imbalance") or 0.0)
        flow = _reported_trade_imbalance(latest)
        age_seconds = max(0.0, (current_time - observed_at).total_seconds())

        price_score = _clamp(
            abs(lookback_return_pct or 0.0) / min_abs_move_pct / 3.0,
            0.0,
            1.0,
        )
        funding_score = _clamp(
            max(float(funding_rate or 0.0), 0.0) / min_abs_funding_rate / 3.0,
            0.0,
            1.0,
        )
        oi_score = _clamp(
            max(float(oi_change_pct or 0.0), 0.0) / min_oi_change_pct / 3.0,
            0.0,
            1.0,
        )
        spread_quality = _clamp(1.0 - (spread_pct / max_spread_pct), 0.0, 1.0)
        flow_score = _clamp(abs(flow), 0.0, 1.0)
        book_score = _clamp(abs(book), 0.0, 1.0)
        dislocation_score = round(
            price_score * 0.35
            + funding_score * 0.25
            + oi_score * 0.25
            + spread_quality * 0.05
            + flow_score * 0.05
            + book_score * 0.05,
            4,
        )

        signal_ready, reason = _long_signal_state(
            age_seconds=age_seconds,
            fresh_seconds=fresh_seconds,
            lookback_return_pct=lookback_return_pct,
            funding_rate=funding_rate,
            oi_change_pct=oi_change_pct,
            spread_pct=spread_pct,
            min_abs_move_pct=min_abs_move_pct,
            min_abs_funding_rate=min_abs_funding_rate,
            min_oi_change_pct=min_oi_change_pct,
            max_spread_pct=max_spread_pct,
        )
        readiness = "ready" if signal_ready else ("watch" if dislocation_score >= 0.55 else "cold")

        rows.append(
            MarketDislocationRow(
                inst_id=inst_id,
                observed_at=observed_at,
                age_seconds=age_seconds,
                price=price,
                lookback_return_pct=lookback_return_pct,
                funding_rate=funding_rate,
                oi_change_pct=oi_change_pct,
                spread_pct=spread_pct,
                book_imbalance=book,
                trade_imbalance=flow,
                price_flush_score=round(price_score, 4),
                funding_heat_score=round(funding_score, 4),
                oi_buildup_score=round(oi_score, 4),
                spread_quality_score=round(spread_quality, 4),
                flow_imbalance_score=round(flow_score, 4),
                book_imbalance_score=round(book_score, 4),
                dislocation_score=dislocation_score,
                candidate_side="long",
                readiness=readiness,
                signal_ready=signal_ready,
                reason=reason,
            )
        )

    return sorted(
        rows,
        key=lambda row: (row.signal_ready, row.dislocation_score, -row.age_seconds),
        reverse=True,
    )


def _long_signal_state(
    *,
    age_seconds: float,
    fresh_seconds: int,
    lookback_return_pct: float | None,
    funding_rate: float | None,
    oi_change_pct: float | None,
    spread_pct: float,
    min_abs_move_pct: float,
    min_abs_funding_rate: float,
    min_oi_change_pct: float,
    max_spread_pct: float,
) -> tuple[bool, str]:
    blockers: list[str] = []
    if age_seconds > fresh_seconds:
        blockers.append("snapshot stale")
    if lookback_return_pct is None:
        blockers.append("not enough price history")
    elif lookback_return_pct > -min_abs_move_pct:
        blockers.append("drop not large enough")
    if funding_rate is None:
        blockers.append("funding missing")
    elif funding_rate < min_abs_funding_rate:
        blockers.append("funding not crowded long")
    if oi_change_pct is None:
        blockers.append("OI history missing")
    elif oi_change_pct < min_oi_change_pct:
        blockers.append("OI buildup not enough")
    if spread_pct > max_spread_pct:
        blockers.append("spread too wide")
    if blockers:
        return False, ", ".join(blockers)
    return True, "long flush reversal candidate"


def _snapshots_by_instrument(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in snapshots:
        grouped.setdefault(str(row["inst_id"]), []).append(row)
    return {
        inst_id: sorted(rows, key=lambda item: item["observed_at"])
        for inst_id, rows in grouped.items()
        if rows
    }


def _reference_snapshot(
    ordered: Sequence[Mapping[str, Any]],
    latest_at: datetime,
    lookback_seconds: int,
) -> Mapping[str, Any] | None:
    cutoff_ts = latest_at.timestamp() - lookback_seconds
    reference: Mapping[str, Any] | None = None
    for row in ordered:
        if _ensure_aware(row["observed_at"]).timestamp() <= cutoff_ts:
            reference = row
        else:
            break
    return reference or (ordered[0] if len(ordered) > 1 else None)


def _snapshot_price(snapshot: Mapping[str, Any] | None) -> float:
    if snapshot is None:
        return 0.0
    return float(snapshot.get("mid_price") or snapshot.get("last_price") or 0.0)


def _snapshot_oi(snapshot: Mapping[str, Any] | None) -> float:
    if snapshot is None:
        return 0.0
    return float(snapshot.get("open_interest_usd") or snapshot.get("open_interest") or 0.0)


def _reported_trade_imbalance(snapshot: Mapping[str, Any]) -> float:
    buy = float(snapshot.get("reported_buy_notional") or 0.0)
    sell = float(snapshot.get("reported_sell_notional") or 0.0)
    total = buy + sell
    if total <= 0.0:
        return 0.0
    return (buy - sell) / total


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
