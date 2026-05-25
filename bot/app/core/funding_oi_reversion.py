from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class FundingOiFlushFeatures:
    lookback_return_pct: float
    funding_rate: float
    oi_change_pct: float
    reported_trade_imbalance: float
    book_imbalance: float
    spread_pct: float
    setup: str


@dataclass(frozen=True)
class FundingOiFlushEvent:
    inst_id: str
    occurred_at: datetime
    candidate_side: str
    score: float
    snapshot_id: Any | None
    features: FundingOiFlushFeatures


@dataclass(frozen=True)
class FundingOiFlushOutcome:
    horizon_seconds: int
    entry_at: datetime
    exit_at: datetime
    entry_price: float
    exit_price: float
    gross_return_pct: float
    cost_adjusted_edge_pct: float
    max_adverse_excursion_pct: float
    max_favorable_excursion_pct: float
    label: int


def build_funding_oi_flush_events(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    lookback_seconds: int = 300,
    min_abs_move_pct: float = 0.5,
    min_abs_funding_rate: float = 0.00005,
    min_oi_change_pct: float = 0.2,
    cooldown_seconds: int = 300,
    mode: str = "both",
) -> list[FundingOiFlushEvent]:
    """Find research-only mean-reversion candidates after crowded perp flushes.

    Long setup:
    - price has dropped over the lookback window
    - funding is positive enough to imply crowded longs
    - open interest increased enough to imply positioning pressure

    Short setup is the symmetric version for crowded shorts.
    """
    if lookback_seconds <= 0:
        raise ValueError("lookback_seconds must be positive")
    if min_abs_move_pct <= 0.0:
        raise ValueError("min_abs_move_pct must be positive")
    if min_abs_funding_rate < 0.0:
        raise ValueError("min_abs_funding_rate cannot be negative")
    if min_oi_change_pct < 0.0:
        raise ValueError("min_oi_change_pct cannot be negative")
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds cannot be negative")
    if mode not in {"both", "long", "short"}:
        raise ValueError("mode must be one of: both, long, short")

    events: list[FundingOiFlushEvent] = []
    cooldown = timedelta(seconds=cooldown_seconds)
    for inst_id, ordered in _snapshots_by_instrument(snapshots).items():
        last_event_at: dict[str, datetime] = {}
        reference_index = 0
        for index, current in enumerate(ordered):
            cutoff = current["observed_at"] - timedelta(seconds=lookback_seconds)
            while reference_index + 1 < index and ordered[reference_index + 1]["observed_at"] <= cutoff:
                reference_index += 1

            if reference_index >= index or ordered[reference_index]["observed_at"] > cutoff:
                continue

            reference = ordered[reference_index]
            current_price = _snapshot_price(current)
            reference_price = _snapshot_price(reference)
            current_oi = _snapshot_oi(current)
            reference_oi = _snapshot_oi(reference)
            funding_rate = current.get("funding_rate")
            if current_price <= 0.0 or reference_price <= 0.0 or current_oi <= 0.0 or reference_oi <= 0.0:
                continue
            if funding_rate is None:
                continue

            lookback_return_pct = ((current_price / reference_price) - 1.0) * 100.0
            oi_change_pct = ((current_oi / reference_oi) - 1.0) * 100.0
            candidate_side: str | None = None
            setup = ""
            if (
                mode in {"both", "long"}
                and lookback_return_pct <= -min_abs_move_pct
                and float(funding_rate) >= min_abs_funding_rate
                and oi_change_pct >= min_oi_change_pct
            ):
                candidate_side = "long"
                setup = "long_flush_reversal"
            elif (
                mode in {"both", "short"}
                and lookback_return_pct >= min_abs_move_pct
                and float(funding_rate) <= -min_abs_funding_rate
                and oi_change_pct >= min_oi_change_pct
            ):
                candidate_side = "short"
                setup = "short_squeeze_reversion"

            if candidate_side is None:
                continue
            previous = last_event_at.get(candidate_side)
            if previous is not None and current["observed_at"] - previous < cooldown:
                continue

            features = FundingOiFlushFeatures(
                lookback_return_pct=lookback_return_pct,
                funding_rate=float(funding_rate),
                oi_change_pct=oi_change_pct,
                reported_trade_imbalance=_reported_trade_imbalance(current),
                book_imbalance=float(current.get("book_imbalance", 0.0) or 0.0),
                spread_pct=float(current.get("spread_pct", 0.0) or 0.0),
                setup=setup,
            )
            event = FundingOiFlushEvent(
                inst_id=inst_id,
                occurred_at=current["observed_at"],
                candidate_side=candidate_side,
                score=_event_score(
                    lookback_return_pct=lookback_return_pct,
                    funding_rate=float(funding_rate),
                    oi_change_pct=oi_change_pct,
                    min_abs_move_pct=min_abs_move_pct,
                    min_abs_funding_rate=max(min_abs_funding_rate, 1e-12),
                    min_oi_change_pct=max(min_oi_change_pct, 1e-12),
                ),
                snapshot_id=current.get("snapshot_id"),
                features=features,
            )
            events.append(event)
            last_event_at[candidate_side] = current["observed_at"]

    return events


def label_funding_oi_flush_outcomes(
    event: FundingOiFlushEvent,
    snapshots: Sequence[Mapping[str, Any]],
    *,
    horizons_seconds: Sequence[int] = (60, 300, 900),
    entry_delay_seconds: int = 20,
    round_trip_cost_pct: float = 0.06,
) -> list[FundingOiFlushOutcome]:
    if entry_delay_seconds < 0:
        raise ValueError("entry_delay_seconds cannot be negative")
    if round_trip_cost_pct < 0.0:
        raise ValueError("round_trip_cost_pct cannot be negative")

    ordered = _snapshots_by_instrument(snapshots).get(event.inst_id, [])
    entry = _first_at_or_after(ordered, event.occurred_at + timedelta(seconds=entry_delay_seconds))
    if entry is None:
        return []
    entry_price = _snapshot_price(entry)
    if entry_price <= 0.0:
        return []

    outcomes: list[FundingOiFlushOutcome] = []
    for horizon in horizons_seconds:
        if horizon <= 0:
            raise ValueError("horizons_seconds must be positive")

        exit_row = _first_at_or_after(ordered, entry["observed_at"] + timedelta(seconds=horizon))
        if exit_row is None:
            continue

        exit_price = _snapshot_price(exit_row)
        if exit_price <= 0.0:
            continue

        path = [
            row
            for row in ordered
            if entry["observed_at"] <= row["observed_at"] <= exit_row["observed_at"]
        ]
        path_returns = [
            _side_return_pct(entry_price, _snapshot_price(row), event.candidate_side)
            for row in path
            if _snapshot_price(row) > 0.0
        ]
        gross_return = _side_return_pct(entry_price, exit_price, event.candidate_side)
        edge = gross_return - round_trip_cost_pct
        outcomes.append(
            FundingOiFlushOutcome(
                horizon_seconds=int(horizon),
                entry_at=entry["observed_at"],
                exit_at=exit_row["observed_at"],
                entry_price=entry_price,
                exit_price=exit_price,
                gross_return_pct=gross_return,
                cost_adjusted_edge_pct=edge,
                max_adverse_excursion_pct=min(path_returns) if path_returns else gross_return,
                max_favorable_excursion_pct=max(path_returns) if path_returns else gross_return,
                label=1 if edge > 0.0 else (-1 if edge < 0.0 else 0),
            )
        )
    return outcomes


def summarize_funding_oi_flush_outcomes(
    events: Sequence[FundingOiFlushEvent],
    outcomes_by_event: Sequence[tuple[FundingOiFlushEvent, Sequence[FundingOiFlushOutcome]]],
) -> dict[str, Any]:
    all_outcomes = [outcome for _, outcomes in outcomes_by_event for outcome in outcomes]
    by_horizon: dict[int, list[FundingOiFlushOutcome]] = {}
    by_side: dict[str, list[FundingOiFlushOutcome]] = {}
    by_instrument: dict[str, list[FundingOiFlushOutcome]] = {}

    for event, outcomes in outcomes_by_event:
        for outcome in outcomes:
            by_horizon.setdefault(outcome.horizon_seconds, []).append(outcome)
            by_side.setdefault(event.candidate_side, []).append(outcome)
            by_instrument.setdefault(event.inst_id, []).append(outcome)

    return {
        "event_count": len(events),
        "outcome_count": len(all_outcomes),
        "overall": _summarize_outcome_rows(all_outcomes),
        "by_horizon": {
            str(horizon): _summarize_outcome_rows(rows)
            for horizon, rows in sorted(by_horizon.items())
        },
        "by_side": {
            side: _summarize_outcome_rows(rows)
            for side, rows in sorted(by_side.items())
        },
        "by_instrument": {
            inst_id: _summarize_outcome_rows(rows)
            for inst_id, rows in sorted(
                by_instrument.items(),
                key=lambda item: (len(item[1]), mean(row.cost_adjusted_edge_pct for row in item[1])),
                reverse=True,
            )
        },
    }


def _summarize_outcome_rows(rows: Sequence[FundingOiFlushOutcome]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "avg_gross_return_pct": 0.0,
            "avg_cost_adjusted_edge_pct": 0.0,
            "median_cost_adjusted_edge_pct": 0.0,
            "win_rate_pct": 0.0,
            "best_edge_pct": 0.0,
            "worst_edge_pct": 0.0,
            "avg_mae_pct": 0.0,
            "avg_mfe_pct": 0.0,
        }

    edges = [row.cost_adjusted_edge_pct for row in rows]
    gross = [row.gross_return_pct for row in rows]
    wins = [row for row in rows if row.cost_adjusted_edge_pct > 0.0]
    return {
        "count": len(rows),
        "avg_gross_return_pct": mean(gross),
        "avg_cost_adjusted_edge_pct": mean(edges),
        "median_cost_adjusted_edge_pct": median(edges),
        "win_rate_pct": (len(wins) / len(rows)) * 100.0,
        "best_edge_pct": max(edges),
        "worst_edge_pct": min(edges),
        "avg_mae_pct": mean(row.max_adverse_excursion_pct for row in rows),
        "avg_mfe_pct": mean(row.max_favorable_excursion_pct for row in rows),
    }


def _snapshots_by_instrument(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in snapshots:
        grouped.setdefault(str(row["inst_id"]), []).append(row)
    return {
        inst_id: sorted(rows, key=lambda row: row["observed_at"])
        for inst_id, rows in grouped.items()
    }


def _first_at_or_after(snapshots: Sequence[Mapping[str, Any]], timestamp: datetime) -> Mapping[str, Any] | None:
    for row in snapshots:
        if row["observed_at"] >= timestamp:
            return row
    return None


def _snapshot_price(snapshot: Mapping[str, Any]) -> float:
    return float(snapshot.get("mid_price") or snapshot.get("last_price") or 0.0)


def _snapshot_oi(snapshot: Mapping[str, Any]) -> float:
    return float(snapshot.get("open_interest_usd") or snapshot.get("open_interest") or 0.0)


def _reported_trade_imbalance(snapshot: Mapping[str, Any]) -> float:
    buy = float(snapshot.get("reported_buy_notional") or 0.0)
    sell = float(snapshot.get("reported_sell_notional") or 0.0)
    total = buy + sell
    if total <= 0.0:
        return 0.0
    return (buy - sell) / total


def _side_return_pct(entry_price: float, observed_price: float, side: str) -> float:
    if entry_price <= 0.0 or observed_price <= 0.0:
        return 0.0
    if side == "long":
        return ((observed_price / entry_price) - 1.0) * 100.0
    if side == "short":
        return ((entry_price / observed_price) - 1.0) * 100.0
    return 0.0


def _event_score(
    *,
    lookback_return_pct: float,
    funding_rate: float,
    oi_change_pct: float,
    min_abs_move_pct: float,
    min_abs_funding_rate: float,
    min_oi_change_pct: float,
) -> float:
    move_component = min(abs(lookback_return_pct) / min_abs_move_pct, 3.0) / 3.0
    funding_component = min(abs(funding_rate) / min_abs_funding_rate, 3.0) / 3.0
    oi_component = min(oi_change_pct / min_oi_change_pct, 3.0) / 3.0
    return round((move_component * 0.40) + (funding_component * 0.30) + (oi_component * 0.30), 8)
