from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CrowdedUnwindFeatures:
    oi_zscore: float
    funding_zscore: float
    book_imbalance: float
    book_thinning_score: float
    exchange_reported_trade_side_imbalance: float
    price_stall_score: float
    crowding_score: float
    candidate_side: str
    data_quality_flags: dict[str, Any]


@dataclass(frozen=True)
class ResearchEventCandidate:
    inst_id: str
    occurred_at: datetime
    candidate_side: str
    crowding_score: float
    features: CrowdedUnwindFeatures


@dataclass(frozen=True)
class EventOutcome:
    horizon_seconds: int
    future_return_pct: float
    cost_adjusted_edge_pct: float
    max_adverse_excursion_pct: float
    max_favorable_excursion_pct: float
    label: int


PROMOTION_GATES: dict[str, float | int] = {
    "min_events_total": 300,
    "min_events_per_oos_fold": 50,
    "min_oos_folds": 4,
    "min_net_expectancy_pct": 0.03,
    "max_worst_oos_expectancy_pct": -0.02,
}


def rolling_zscore(values: Sequence[float], current: float | None = None) -> float:
    if not values:
        return 0.0
    baseline = [float(value) for value in values]
    observed = float(baseline[-1] if current is None else current)
    if len(baseline) < 2:
        return 0.0
    sigma = pstdev(baseline)
    if sigma == 0.0:
        return 0.0
    return (observed - mean(baseline)) / sigma


def book_imbalance(bid_depth_notional: float, ask_depth_notional: float) -> float:
    total = float(bid_depth_notional) + float(ask_depth_notional)
    if total <= 0.0:
        return 0.0
    return (float(bid_depth_notional) - float(ask_depth_notional)) / total


def book_thinning_score(current_visible_depth: float, depth_history: Sequence[float]) -> float:
    positive_depths = [float(value) for value in depth_history if float(value) > 0.0]
    if not positive_depths:
        return 0.0
    baseline = mean(positive_depths)
    if baseline <= 0.0:
        return 0.0
    thinning = 1.0 - (float(current_visible_depth) / baseline)
    return _clamp(thinning, 0.0, 1.0)


def exchange_reported_trade_side_imbalance(buy_notional: float, sell_notional: float) -> float:
    total = float(buy_notional) + float(sell_notional)
    if total <= 0.0:
        return 0.0
    return (float(buy_notional) - float(sell_notional)) / total


def price_stall_score(prices: Sequence[float], *, max_abs_return_pct: float = 0.03) -> float:
    clean_prices = [float(price) for price in prices if float(price) > 0.0]
    if len(clean_prices) < 2:
        return 0.0
    start = clean_prices[0]
    end = clean_prices[-1]
    abs_return_pct = abs((end / start - 1.0) * 100.0)
    if max_abs_return_pct <= 0.0:
        raise ValueError("max_abs_return_pct must be positive")
    return _clamp(1.0 - (abs_return_pct / max_abs_return_pct), 0.0, 1.0)


def compute_crowded_unwind_features(
    *,
    oi_values: Sequence[float],
    funding_values: Sequence[float],
    bid_depth_notional: float,
    ask_depth_notional: float,
    visible_depth_history: Sequence[float],
    reported_buy_notional: float,
    reported_sell_notional: float,
    prices: Sequence[float],
    min_abs_flow_imbalance: float = 0.15,
    min_abs_book_imbalance: float = 0.10,
) -> CrowdedUnwindFeatures:
    oi_z = rolling_zscore(oi_values)
    funding_z = rolling_zscore(funding_values)
    book = book_imbalance(bid_depth_notional, ask_depth_notional)
    current_visible_depth = min(float(bid_depth_notional), float(ask_depth_notional))
    thinning = book_thinning_score(current_visible_depth, visible_depth_history)
    flow = exchange_reported_trade_side_imbalance(reported_buy_notional, reported_sell_notional)
    stall = price_stall_score(prices)
    candidate_side = _candidate_side(flow_imbalance=flow, book=book)

    data_quality_flags: dict[str, Any] = {}
    if abs(flow) < min_abs_flow_imbalance:
        data_quality_flags["weak_exchange_reported_trade_side_imbalance"] = True
    if abs(book) < min_abs_book_imbalance:
        data_quality_flags["weak_book_imbalance"] = True
    if not oi_values:
        data_quality_flags["missing_open_interest"] = True
    if not funding_values:
        data_quality_flags["missing_funding"] = True
    if len(prices) < 2:
        data_quality_flags["missing_price_stall_window"] = True

    crowding_score = (
        min(abs(oi_z), 3.0) / 3.0 * 0.25
        + min(abs(funding_z), 3.0) / 3.0 * 0.20
        + abs(flow) * 0.20
        + abs(book) * 0.15
        + thinning * 0.10
        + stall * 0.10
    )

    return CrowdedUnwindFeatures(
        oi_zscore=oi_z,
        funding_zscore=funding_z,
        book_imbalance=book,
        book_thinning_score=thinning,
        exchange_reported_trade_side_imbalance=flow,
        price_stall_score=stall,
        crowding_score=round(crowding_score, 8),
        candidate_side=candidate_side,
        data_quality_flags=data_quality_flags,
    )


def build_event_candidates(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    min_crowding_score: float = 0.55,
    lookback: int = 12,
) -> list[ResearchEventCandidate]:
    if lookback < 2:
        raise ValueError("lookback must be at least 2")

    candidates: list[ResearchEventCandidate] = []
    for ordered in _snapshots_by_instrument(snapshots).values():
        for index in range(lookback - 1, len(ordered)):
            window = ordered[index - lookback + 1 : index + 1]
            current = ordered[index]
            features = compute_crowded_unwind_features(
                oi_values=[_optional_float(row.get("open_interest")) for row in window if row.get("open_interest") is not None],
                funding_values=[_optional_float(row.get("funding_rate")) for row in window if row.get("funding_rate") is not None],
                bid_depth_notional=float(current.get("bid_depth_notional", 0.0)),
                ask_depth_notional=float(current.get("ask_depth_notional", 0.0)),
                visible_depth_history=[
                    min(float(row.get("bid_depth_notional", 0.0)), float(row.get("ask_depth_notional", 0.0)))
                    for row in window
                ],
                reported_buy_notional=float(current.get("reported_buy_notional", 0.0)),
                reported_sell_notional=float(current.get("reported_sell_notional", 0.0)),
                prices=[float(row.get("mid_price") or row.get("last_price") or 0.0) for row in window],
            )
            if features.crowding_score < min_crowding_score or features.candidate_side == "neutral":
                continue
            candidates.append(
                ResearchEventCandidate(
                    inst_id=str(current["inst_id"]),
                    occurred_at=current["observed_at"],
                    candidate_side=features.candidate_side,
                    crowding_score=features.crowding_score,
                    features=features,
                )
            )
    return candidates


def label_event_outcomes(
    event: ResearchEventCandidate,
    snapshots: Sequence[Mapping[str, Any]],
    *,
    horizons_seconds: Sequence[int] = (60, 300, 900),
    fee_pct: float = 0.01,
    slippage_pct: float = 0.01,
    latency_haircut_pct: float = 0.01,
) -> list[EventOutcome]:
    ordered = sorted(
        [row for row in snapshots if str(row["inst_id"]) == event.inst_id],
        key=lambda row: row["observed_at"],
    )
    entry = _first_at_or_after(ordered, event.occurred_at)
    if entry is None:
        return []

    entry_price = _snapshot_price(entry)
    if entry_price <= 0.0:
        return []

    total_cost_pct = fee_pct + slippage_pct + latency_haircut_pct
    outcomes: list[EventOutcome] = []
    for horizon in horizons_seconds:
        if horizon <= 0:
            raise ValueError("horizons_seconds must be positive")
        cutoff = event.occurred_at + timedelta(seconds=horizon)
        horizon_rows = [row for row in ordered if event.occurred_at < row["observed_at"] <= cutoff]
        if not horizon_rows:
            continue
        terminal_price = _snapshot_price(horizon_rows[-1])
        returns = [_side_return_pct(entry_price, _snapshot_price(row), event.candidate_side) for row in horizon_rows]
        future_return = _side_return_pct(entry_price, terminal_price, event.candidate_side)
        edge = future_return - total_cost_pct
        outcomes.append(
            EventOutcome(
                horizon_seconds=horizon,
                future_return_pct=future_return,
                cost_adjusted_edge_pct=edge,
                max_adverse_excursion_pct=min(returns),
                max_favorable_excursion_pct=max(returns),
                label=1 if edge > 0.0 else (-1 if edge < 0.0 else 0),
            )
        )
    return outcomes


def promotion_gate_report(
    *,
    total_events: int,
    oos_fold_event_counts: Sequence[int],
    net_expectancy_pct: float,
    bootstrap_lower_bound_pct: float,
    robust_instrument_count: int,
    robust_adjacent_horizon_count: int,
    worst_oos_expectancy_pct: float,
    phase_1a_quality_passed: bool,
) -> dict[str, Any]:
    fold_count = len(oos_fold_event_counts)
    checks = {
        "min_events_total": total_events >= PROMOTION_GATES["min_events_total"],
        "min_events_per_oos_fold": all(count >= PROMOTION_GATES["min_events_per_oos_fold"] for count in oos_fold_event_counts),
        "min_oos_folds": fold_count >= PROMOTION_GATES["min_oos_folds"],
        "min_net_expectancy_pct": net_expectancy_pct > PROMOTION_GATES["min_net_expectancy_pct"],
        "bootstrap_lower_bound_positive": bootstrap_lower_bound_pct > 0.0,
        "instrument_robustness": robust_instrument_count >= 2,
        "adjacent_horizon_robustness": robust_adjacent_horizon_count >= 2,
        "worst_oos_expectancy_floor": worst_oos_expectancy_pct >= PROMOTION_GATES["max_worst_oos_expectancy_pct"],
        "phase_1a_quality_passed": phase_1a_quality_passed,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": {
            "total_events": total_events,
            "oos_fold_count": fold_count,
            "oos_fold_event_counts": list(oos_fold_event_counts),
            "net_expectancy_pct": net_expectancy_pct,
            "bootstrap_lower_bound_pct": bootstrap_lower_bound_pct,
            "robust_instrument_count": robust_instrument_count,
            "robust_adjacent_horizon_count": robust_adjacent_horizon_count,
            "worst_oos_expectancy_pct": worst_oos_expectancy_pct,
        },
    }


def _candidate_side(*, flow_imbalance: float, book: float) -> str:
    if flow_imbalance > 0.0 and book <= 0.0:
        return "short"
    if flow_imbalance < 0.0 and book >= 0.0:
        return "long"
    if flow_imbalance > 0.0:
        return "short"
    if flow_imbalance < 0.0:
        return "long"
    return "neutral"


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


def _side_return_pct(entry_price: float, observed_price: float, side: str) -> float:
    if entry_price <= 0.0 or observed_price <= 0.0:
        return 0.0
    if side == "long":
        return ((observed_price / entry_price) - 1.0) * 100.0
    if side == "short":
        return ((entry_price / observed_price) - 1.0) * 100.0
    return 0.0


def _optional_float(value: Any) -> float:
    return float(value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def summarize_outcomes(outcomes: Iterable[EventOutcome]) -> dict[str, Any]:
    rows = list(outcomes)
    if not rows:
        return {
            "event_count": 0,
            "net_expectancy_pct": 0.0,
            "worst_edge_pct": 0.0,
            "best_edge_pct": 0.0,
        }
    edges = [row.cost_adjusted_edge_pct for row in rows]
    return {
        "event_count": len(rows),
        "net_expectancy_pct": mean(edges),
        "worst_edge_pct": min(edges),
        "best_edge_pct": max(edges),
    }
