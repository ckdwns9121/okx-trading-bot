from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.funding_oi_reversion import (
    build_funding_oi_flush_events,
    label_funding_oi_flush_outcomes,
    summarize_funding_oi_flush_outcomes,
)
from scripts import run_funding_oi_reversion_event_study as event_study


def _snapshot(
    *,
    index: int,
    price: float,
    funding_rate: float,
    open_interest_usd: float,
    inst_id: str = "AI-USDT-SWAP",
):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "inst_id": inst_id,
        "observed_at": start + timedelta(seconds=60 * index),
        "mid_price": price,
        "last_price": price,
        "spread_pct": 0.04,
        "bid_depth_notional": 10_000.0,
        "ask_depth_notional": 8_000.0,
        "book_imbalance": 0.1111,
        "reported_buy_notional": 1_000.0,
        "reported_sell_notional": 4_000.0,
        "funding_rate": funding_rate,
        "open_interest": open_interest_usd / price,
        "open_interest_usd": open_interest_usd,
    }


def test_build_funding_oi_flush_events_detects_long_setup_and_cooldown() -> None:
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 99.0, 99.1, 99.2, 99.4, 99.5, 99.8]
    snapshots = [
        _snapshot(index=index, price=price, funding_rate=0.00008, open_interest_usd=1_000_000.0 + index * 1_000.0)
        for index, price in enumerate(prices)
    ]

    events = build_funding_oi_flush_events(
        snapshots,
        lookback_seconds=300,
        min_abs_move_pct=0.5,
        min_abs_funding_rate=0.00005,
        min_oi_change_pct=0.2,
        cooldown_seconds=600,
    )

    assert len(events) == 1
    assert events[0].candidate_side == "long"
    assert events[0].features.setup == "long_flush_reversal"
    assert events[0].features.lookback_return_pct == pytest.approx(-1.0)
    assert events[0].features.oi_change_pct > 0.2
    assert events[0].score > 0.0


def test_build_funding_oi_flush_events_detects_symmetric_short_setup() -> None:
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 101.0, 101.2]
    snapshots = [
        _snapshot(index=index, price=price, funding_rate=-0.00008, open_interest_usd=1_000_000.0 + index * 1_000.0)
        for index, price in enumerate(prices)
    ]

    events = build_funding_oi_flush_events(
        snapshots,
        lookback_seconds=300,
        min_abs_move_pct=0.5,
        min_abs_funding_rate=0.00005,
        min_oi_change_pct=0.2,
        mode="short",
    )

    assert len(events) == 1
    assert events[0].candidate_side == "short"
    assert events[0].features.setup == "short_squeeze_reversion"


def test_label_funding_oi_flush_outcomes_uses_delayed_entry_and_costs() -> None:
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 99.0, 99.1, 99.3, 99.6, 99.8, 100.0, 100.2]
    snapshots = [
        _snapshot(index=index, price=price, funding_rate=0.00008, open_interest_usd=1_000_000.0 + index * 1_000.0)
        for index, price in enumerate(prices)
    ]
    event = build_funding_oi_flush_events(
        snapshots,
        lookback_seconds=300,
        min_abs_move_pct=0.5,
        min_abs_funding_rate=0.00005,
        min_oi_change_pct=0.2,
        cooldown_seconds=600,
    )[0]

    outcomes = label_funding_oi_flush_outcomes(
        event,
        snapshots,
        horizons_seconds=(300,),
        entry_delay_seconds=60,
        round_trip_cost_pct=0.06,
    )

    assert len(outcomes) == 1
    assert outcomes[0].entry_at == snapshots[6]["observed_at"]
    assert outcomes[0].exit_at == snapshots[11]["observed_at"]
    assert outcomes[0].gross_return_pct == pytest.approx((100.2 / 99.1 - 1.0) * 100.0)
    assert outcomes[0].cost_adjusted_edge_pct == pytest.approx(outcomes[0].gross_return_pct - 0.06)
    assert outcomes[0].label == 1


def test_summarize_funding_oi_flush_outcomes_groups_horizons_and_instruments() -> None:
    snapshots = [
        _snapshot(index=index, price=price, funding_rate=0.00008, open_interest_usd=1_000_000.0 + index * 1_000.0)
        for index, price in enumerate([100.0, 100.0, 100.0, 100.0, 100.0, 99.0, 99.1, 99.4, 99.8, 100.1, 100.3, 100.4])
    ]
    event = build_funding_oi_flush_events(snapshots, cooldown_seconds=600)[0]
    outcomes = label_funding_oi_flush_outcomes(event, snapshots, horizons_seconds=(60, 300), entry_delay_seconds=60)

    summary = summarize_funding_oi_flush_outcomes([event], [(event, outcomes)])

    assert summary["event_count"] == 1
    assert summary["outcome_count"] == 2
    assert summary["by_horizon"]["60"]["count"] == 1
    assert summary["by_instrument"]["AI-USDT-SWAP"]["count"] == 2


def test_funding_oi_reversion_script_dry_run_report_is_research_only(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = event_study.main(["--dry-run", "--lookback-seconds", "300"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"research_only": true' in output
    assert '"event_count":' in output
