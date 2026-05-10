from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.microstructure import evaluate_microstructure_gate, should_allow_microstructure_entry


def test_microstructure_gate_allows_fresh_tight_buy_snapshot() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    payload = evaluate_microstructure_gate(
        side="buy",
        order_notional=250.0,
        max_spread_pct=0.5,
        min_visible_depth_notional=100.0,
        max_market_data_age_seconds=5.0,
        market_data={
            "best_bid": 100.0,
            "best_ask": 100.2,
            "ask_depth_notional": 500.0,
            "timestamp": int((now - timedelta(seconds=2)).timestamp() * 1000),
        },
        now=now,
    )

    assert payload["allow"] is True
    assert payload["reason"] == "ok"
    assert payload["expected_price"] == pytest.approx(100.2)
    assert payload["spread_pct"] == pytest.approx(((100.2 - 100.0) / 100.1) * 100.0)
    assert payload["visible_depth"] == pytest.approx(500.0)
    assert payload["market_data_age_seconds"] == pytest.approx(2.0)
    assert payload["stale"] is False


def test_microstructure_gate_blocks_when_market_data_is_stale() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    allowed, payload = should_allow_microstructure_entry(
        side="sell",
        order_notional=125.0,
        max_spread_pct=0.5,
        min_visible_depth_notional=100.0,
        max_market_data_age_seconds=1.0,
        market_data={
            "best_bid": 99.8,
            "best_ask": 100.0,
            "bid_depth_notional": 350.0,
            "timestamp": int((now - timedelta(seconds=3)).timestamp() * 1000),
        },
        now=now,
    )

    assert allowed is False
    assert payload["reason"] == "stale_market_data"
    assert payload["expected_price"] == pytest.approx(99.8)
    assert payload["visible_depth"] == pytest.approx(350.0)
    assert payload["market_data_age_seconds"] == pytest.approx(3.0)
    assert payload["stale"] is True


def test_microstructure_gate_blocks_when_spread_or_depth_limits_fail() -> None:
    spread_payload = evaluate_microstructure_gate(
        side="buy",
        order_notional=100.0,
        max_spread_pct=0.2,
        min_visible_depth_notional=50.0,
        max_market_data_age_seconds=10.0,
        best_bid=100.0,
        best_ask=101.0,
        visible_depth=500.0,
        market_data_timestamp=datetime.now(timezone.utc),
    )
    depth_payload = evaluate_microstructure_gate(
        side="short",
        order_notional=100.0,
        max_spread_pct=2.0,
        min_visible_depth_notional=200.0,
        max_market_data_age_seconds=10.0,
        market_data={
            "best_bid": 100.0,
            "best_ask": 100.1,
            "bid_depth_notional": 120.0,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
    )

    assert spread_payload["allow"] is False
    assert spread_payload["reason"] == "spread_too_wide"
    assert depth_payload["allow"] is False
    assert depth_payload["reason"] == "insufficient_visible_depth"
    assert depth_payload["visible_depth"] == pytest.approx(120.0)
    assert depth_payload["required_visible_depth"] == pytest.approx(200.0)


def test_microstructure_gate_requires_depth_to_cover_order_notional() -> None:
    payload = evaluate_microstructure_gate(
        side="buy",
        order_notional=1_000.0,
        max_spread_pct=1.0,
        min_visible_depth_notional=100.0,
        max_market_data_age_seconds=10.0,
        market_data={
            "best_bid": 100.0,
            "best_ask": 100.1,
            "ask_depth_notional": 900.0,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
    )

    assert payload["allow"] is False
    assert payload["reason"] == "insufficient_visible_depth"
    assert payload["required_visible_depth"] == pytest.approx(1_000.0)
