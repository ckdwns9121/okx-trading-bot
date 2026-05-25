from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

STRATEGY_NAME = "Funding/Basis Arbitrage"
LONG_SPOT_SHORT_PERP = "long_spot_short_perp"
LONG_PERP_SHORT_SPOT = "long_perp_short_spot"
FUNDING_INTERVALS_PER_DAY = 3.0


@dataclass(frozen=True)
class BasisArbitrageRow:
    inst_id: str
    spot_inst_id: str
    observed_at: datetime
    age_seconds: float
    perp_mid_price: float
    spot_mid_price: float
    basis_pct: float
    funding_rate: float | None
    funding_8h_pct: float | None
    estimated_daily_funding_pct: float | None
    perp_spread_pct: float
    spot_spread_pct: float
    estimated_round_trip_cost_pct: float
    net_funding_8h_after_cost_pct: float | None
    candidate_side: str
    carry_score: float
    readiness: str
    signal_ready: bool
    reason: str


def spot_inst_id_from_swap(inst_id: str) -> str:
    if not inst_id.endswith("-SWAP"):
        raise ValueError("basis arbitrage instruments must be OKX swap IDs ending in -SWAP")
    return inst_id.removesuffix("-SWAP")


def basis_pct(*, perp_mid_price: float, spot_mid_price: float) -> float:
    if perp_mid_price <= 0.0 or spot_mid_price <= 0.0:
        return 0.0
    return ((perp_mid_price / spot_mid_price) - 1.0) * 100.0


def estimated_daily_funding_pct(funding_rate: float | None) -> float | None:
    if funding_rate is None:
        return None
    return float(funding_rate) * FUNDING_INTERVALS_PER_DAY * 100.0


def build_basis_arbitrage_rows(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    fresh_seconds: int = 180,
    min_abs_funding_rate: float = 0.0001,
    min_abs_basis_pct: float = 0.02,
    max_spread_pct: float = 0.20,
    taker_fee_pct_per_leg: float = 0.05,
) -> list[BasisArbitrageRow]:
    if fresh_seconds <= 0:
        raise ValueError("fresh_seconds must be positive")
    if min_abs_funding_rate < 0.0:
        raise ValueError("min_abs_funding_rate cannot be negative")
    if min_abs_basis_pct < 0.0:
        raise ValueError("min_abs_basis_pct cannot be negative")
    if max_spread_pct <= 0.0:
        raise ValueError("max_spread_pct must be positive")
    if taker_fee_pct_per_leg < 0.0:
        raise ValueError("taker_fee_pct_per_leg cannot be negative")

    current_time = now or datetime.now(timezone.utc)
    latest = _latest_by_inst(snapshots)
    rows = [
        _build_row(
            snapshot,
            now=current_time,
            fresh_seconds=fresh_seconds,
            min_abs_funding_rate=min_abs_funding_rate,
            min_abs_basis_pct=min_abs_basis_pct,
            max_spread_pct=max_spread_pct,
            taker_fee_pct_per_leg=taker_fee_pct_per_leg,
        )
        for snapshot in latest.values()
    ]
    return sorted(rows, key=lambda item: (item.signal_ready, item.carry_score, abs(item.basis_pct)), reverse=True)


def _build_row(
    snapshot: Mapping[str, Any],
    *,
    now: datetime,
    fresh_seconds: int,
    min_abs_funding_rate: float,
    min_abs_basis_pct: float,
    max_spread_pct: float,
    taker_fee_pct_per_leg: float,
) -> BasisArbitrageRow:
    observed_at = _as_datetime(snapshot["observed_at"])
    age_seconds = max(0.0, (now - observed_at).total_seconds())
    funding_rate = _optional_float(snapshot.get("funding_rate"))
    basis = float(snapshot.get("basis_pct") or basis_pct(
        perp_mid_price=float(snapshot.get("perp_mid_price") or 0.0),
        spot_mid_price=float(snapshot.get("spot_mid_price") or 0.0),
    ))
    perp_spread = float(snapshot.get("perp_spread_pct") or 0.0)
    spot_spread = float(snapshot.get("spot_spread_pct") or 0.0)
    round_trip_cost = _estimated_round_trip_cost_pct(
        perp_spread_pct=perp_spread,
        spot_spread_pct=spot_spread,
        taker_fee_pct_per_leg=taker_fee_pct_per_leg,
    )
    funding_8h_pct = (funding_rate * 100.0) if funding_rate is not None else None
    daily_funding = estimated_daily_funding_pct(funding_rate)
    net_after_cost = (abs(funding_8h_pct) - round_trip_cost) if funding_8h_pct is not None else None
    candidate_side = _candidate_side(funding_rate=funding_rate, basis=basis)
    reasons = []
    if age_seconds > fresh_seconds:
        reasons.append("stale snapshot")
    if funding_rate is None:
        reasons.append("funding missing")
    elif abs(funding_rate) < min_abs_funding_rate:
        reasons.append("funding spread too small")
    if abs(basis) < min_abs_basis_pct:
        reasons.append("basis too small")
    if max(perp_spread, spot_spread) > max_spread_pct:
        reasons.append("spread too wide")
    if candidate_side == "none":
        reasons.append("funding and basis disagree")
    if net_after_cost is not None and net_after_cost <= 0.0:
        reasons.append("funding does not cover estimated round trip cost")

    signal_ready = not reasons
    readiness = "ready" if signal_ready else ("watch" if candidate_side != "none" and age_seconds <= fresh_seconds else "cold")
    score = _carry_score(
        funding_rate=funding_rate,
        basis=basis,
        perp_spread_pct=perp_spread,
        spot_spread_pct=spot_spread,
        net_after_cost_pct=net_after_cost,
        min_abs_funding_rate=min_abs_funding_rate,
        min_abs_basis_pct=min_abs_basis_pct,
        max_spread_pct=max_spread_pct,
    )
    return BasisArbitrageRow(
        inst_id=str(snapshot["inst_id"]),
        spot_inst_id=str(snapshot["spot_inst_id"]),
        observed_at=observed_at,
        age_seconds=age_seconds,
        perp_mid_price=float(snapshot.get("perp_mid_price") or 0.0),
        spot_mid_price=float(snapshot.get("spot_mid_price") or 0.0),
        basis_pct=basis,
        funding_rate=funding_rate,
        funding_8h_pct=funding_8h_pct,
        estimated_daily_funding_pct=daily_funding,
        perp_spread_pct=perp_spread,
        spot_spread_pct=spot_spread,
        estimated_round_trip_cost_pct=round_trip_cost,
        net_funding_8h_after_cost_pct=net_after_cost,
        candidate_side=candidate_side,
        carry_score=score,
        readiness=readiness,
        signal_ready=signal_ready,
        reason="; ".join(reasons) if reasons else "ready",
    )


def _candidate_side(*, funding_rate: float | None, basis: float) -> str:
    if funding_rate is None:
        return "none"
    if funding_rate > 0.0 and basis > 0.0:
        return LONG_SPOT_SHORT_PERP
    if funding_rate < 0.0 and basis < 0.0:
        return LONG_PERP_SHORT_SPOT
    return "none"


def _estimated_round_trip_cost_pct(
    *,
    perp_spread_pct: float,
    spot_spread_pct: float,
    taker_fee_pct_per_leg: float,
) -> float:
    spread_cost = max(0.0, perp_spread_pct) + max(0.0, spot_spread_pct)
    fee_cost = taker_fee_pct_per_leg * 4.0
    return spread_cost + fee_cost


def _carry_score(
    *,
    funding_rate: float | None,
    basis: float,
    perp_spread_pct: float,
    spot_spread_pct: float,
    net_after_cost_pct: float | None,
    min_abs_funding_rate: float,
    min_abs_basis_pct: float,
    max_spread_pct: float,
) -> float:
    funding_component = 0.0
    if funding_rate is not None and min_abs_funding_rate > 0.0:
        funding_component = min(abs(funding_rate) / (min_abs_funding_rate * 4.0), 1.0)
    basis_component = min(abs(basis) / max(min_abs_basis_pct * 5.0, 1e-12), 1.0)
    spread_component = 1.0 - min(max(perp_spread_pct, spot_spread_pct) / max_spread_pct, 1.0)
    edge_component = 0.0 if net_after_cost_pct is None else max(min(net_after_cost_pct / 0.10, 1.0), 0.0)
    return max(0.0, min(1.0, (0.35 * funding_component) + (0.25 * basis_component) + (0.20 * spread_component) + (0.20 * edge_component)))


def _latest_by_inst(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for snapshot in snapshots:
        inst_id = str(snapshot["inst_id"])
        observed_at = _as_datetime(snapshot["observed_at"])
        if inst_id not in latest or observed_at > _as_datetime(latest[inst_id]["observed_at"]):
            latest[inst_id] = snapshot
    return latest


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
