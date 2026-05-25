from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.crowded_unwind_research import (
    book_imbalance,
    book_thinning_score,
    build_event_candidates,
    compute_crowded_unwind_features,
    exchange_reported_trade_side_imbalance,
    label_event_outcomes,
    price_stall_score,
    promotion_gate_report,
    rolling_zscore,
)


def test_feature_primitives_are_deterministic_and_fail_closed() -> None:
    assert rolling_zscore([1, 2, 3], 4) == pytest.approx(2.44948974278)
    assert rolling_zscore([1, 1, 1]) == 0.0
    assert book_imbalance(150, 50) == pytest.approx(0.5)
    assert book_imbalance(0, 0) == 0.0
    assert book_thinning_score(50, [100, 100, 100]) == pytest.approx(0.5)
    assert exchange_reported_trade_side_imbalance(90, 10) == pytest.approx(0.8)
    assert price_stall_score([100, 100.01], max_abs_return_pct=0.03) > 0.6


def test_compute_crowded_unwind_features_names_exchange_reported_flow() -> None:
    features = compute_crowded_unwind_features(
        oi_values=[100, 105, 110, 130],
        funding_values=[0.0001, 0.00011, 0.00012, 0.0002],
        bid_depth_notional=10000,
        ask_depth_notional=3000,
        visible_depth_history=[9000, 8500, 8000, 3000],
        reported_buy_notional=9000,
        reported_sell_notional=1000,
        prices=[100.0, 100.01, 100.0, 100.01],
    )

    assert features.exchange_reported_trade_side_imbalance == pytest.approx(0.8)
    assert features.candidate_side == "short"
    assert features.crowding_score > 0.4
    assert "weak_exchange_reported_trade_side_imbalance" not in features.data_quality_flags


def test_build_events_and_label_outcomes_do_not_use_future_features() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = []
    for index in range(12):
        snapshots.append(
            {
                "inst_id": "BTC-USDT-SWAP",
                "observed_at": start + timedelta(seconds=60 * index),
                "mid_price": 100.0 if index < 6 else 100.0 - (index - 5) * 0.2,
                "last_price": 100.0 if index < 6 else 100.0 - (index - 5) * 0.2,
                "bid_depth_notional": 9000.0,
                "ask_depth_notional": 3000.0,
                "reported_buy_notional": 9000.0,
                "reported_sell_notional": 1000.0,
                "funding_rate": 0.0001 + index * 0.00001,
                "open_interest": 100000.0 + index * 1000.0,
            }
        )

    events = build_event_candidates(snapshots[:6], min_crowding_score=0.35, lookback=6)
    assert len(events) == 1
    assert events[0].occurred_at == snapshots[5]["observed_at"]

    outcomes = label_event_outcomes(events[0], snapshots, horizons_seconds=(60, 300), fee_pct=0.0, slippage_pct=0.0)

    assert [outcome.horizon_seconds for outcome in outcomes] == [60, 300]
    assert outcomes[0].label == 1
    assert outcomes[0].future_return_pct > 0
    assert outcomes[1].max_adverse_excursion_pct >= 0


def test_event_study_keeps_feature_and_outcome_windows_per_instrument() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = []
    for index in range(7):
        snapshots.append(
            {
                "inst_id": "BTC-USDT-SWAP",
                "observed_at": start + timedelta(seconds=60 * index),
                "mid_price": 100.0 if index < 6 else 99.97,
                "last_price": 100.0 if index < 6 else 99.97,
                "bid_depth_notional": 9000.0,
                "ask_depth_notional": 3000.0,
                "reported_buy_notional": 9000.0,
                "reported_sell_notional": 1000.0,
                "funding_rate": 0.0001 + index * 0.00001,
                "open_interest": 100000.0 + index * 1000.0,
            }
        )
        snapshots.append(
            {
                "inst_id": "ETH-USDT-SWAP",
                "observed_at": start + timedelta(seconds=(60 * index) + 30),
                "mid_price": 2000.0 - index * 10.0,
                "last_price": 2000.0 - index * 10.0,
                "bid_depth_notional": 10.0,
                "ask_depth_notional": 10.0,
                "reported_buy_notional": 0.0,
                "reported_sell_notional": 0.0,
                "funding_rate": 0.0,
                "open_interest": 1.0,
            }
        )

    events = build_event_candidates(snapshots, min_crowding_score=0.35, lookback=6)

    assert {event.inst_id for event in events} == {"BTC-USDT-SWAP"}
    event = next(event for event in events if event.occurred_at == start + timedelta(seconds=60 * 5))
    outcomes = label_event_outcomes(event, snapshots, horizons_seconds=(60,))
    assert outcomes[0].future_return_pct == pytest.approx(0.0300090027)


def test_promotion_gate_report_fails_closed_until_all_thresholds_pass() -> None:
    failing = promotion_gate_report(
        total_events=299,
        oos_fold_event_counts=[50, 50, 50, 50],
        net_expectancy_pct=0.04,
        bootstrap_lower_bound_pct=0.01,
        robust_instrument_count=2,
        robust_adjacent_horizon_count=2,
        worst_oos_expectancy_pct=-0.01,
        phase_1a_quality_passed=True,
    )
    passing = promotion_gate_report(
        total_events=300,
        oos_fold_event_counts=[50, 51, 52, 53],
        net_expectancy_pct=0.04,
        bootstrap_lower_bound_pct=0.01,
        robust_instrument_count=2,
        robust_adjacent_horizon_count=2,
        worst_oos_expectancy_pct=-0.01,
        phase_1a_quality_passed=True,
    )

    assert failing["passed"] is False
    assert failing["checks"]["min_events_total"] is False
    assert passing["passed"] is True
