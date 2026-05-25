from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.market_dislocation import build_market_dislocation_rows


def _snapshot(
    inst_id: str,
    observed_at: datetime,
    *,
    price: float,
    funding_rate: float,
    oi: float,
    spread_pct: float = 0.02,
) -> dict:
    return {
        "inst_id": inst_id,
        "observed_at": observed_at,
        "mid_price": price,
        "last_price": price,
        "spread_pct": spread_pct,
        "book_imbalance": -0.3,
        "reported_buy_notional": 10.0,
        "reported_sell_notional": 90.0,
        "funding_rate": funding_rate,
        "open_interest_usd": oi,
    }


def test_build_market_dislocation_rows_marks_ready_long_candidate():
    now = datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc)
    snapshots = [
        _snapshot("GRASS-USDT-SWAP", now - timedelta(seconds=320), price=1.0, funding_rate=0.00006, oi=1000),
        _snapshot("GRASS-USDT-SWAP", now - timedelta(seconds=20), price=0.99, funding_rate=0.00008, oi=1010),
    ]

    rows = build_market_dislocation_rows(snapshots, now=now)

    assert len(rows) == 1
    row = rows[0]
    assert row.inst_id == "GRASS-USDT-SWAP"
    assert row.signal_ready is True
    assert row.readiness == "ready"
    assert row.candidate_side == "long"
    assert row.dislocation_score > 0.7


def test_build_market_dislocation_rows_explains_missing_conditions():
    now = datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc)
    snapshots = [
        _snapshot("AIXBT-USDT-SWAP", now - timedelta(seconds=320), price=1.0, funding_rate=0.00001, oi=1000),
        _snapshot("AIXBT-USDT-SWAP", now - timedelta(seconds=20), price=0.999, funding_rate=0.00001, oi=1000),
    ]

    rows = build_market_dislocation_rows(snapshots, now=now)

    assert rows[0].signal_ready is False
    assert "drop not large enough" in rows[0].reason
    assert "funding not crowded long" in rows[0].reason
    assert "OI buildup not enough" in rows[0].reason
