from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.basis_arbitrage import (
    LONG_PERP_SHORT_SPOT,
    LONG_SPOT_SHORT_PERP,
    basis_pct,
    build_basis_arbitrage_rows,
    estimated_daily_funding_pct,
    spot_inst_id_from_swap,
)


def _snapshot(
    inst_id: str,
    observed_at: datetime,
    *,
    perp: float,
    spot: float,
    funding_rate: float,
    perp_spread_pct: float = 0.01,
    spot_spread_pct: float = 0.01,
) -> dict:
    return {
        "inst_id": inst_id,
        "spot_inst_id": spot_inst_id_from_swap(inst_id),
        "observed_at": observed_at,
        "perp_mid_price": perp,
        "spot_mid_price": spot,
        "perp_spread_pct": perp_spread_pct,
        "spot_spread_pct": spot_spread_pct,
        "basis_pct": basis_pct(perp_mid_price=perp, spot_mid_price=spot),
        "funding_rate": funding_rate,
    }


def test_spot_inst_id_from_swap_and_basis_math() -> None:
    assert spot_inst_id_from_swap("BTC-USDT-SWAP") == "BTC-USDT"
    assert basis_pct(perp_mid_price=101.0, spot_mid_price=100.0) == pytest.approx(1.0)
    assert estimated_daily_funding_pct(0.0002) == pytest.approx(0.06)
    with pytest.raises(ValueError):
        spot_inst_id_from_swap("BTC-USDT")


def test_build_basis_arbitrage_rows_marks_ready_short_perp_carry() -> None:
    now = datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "BTC-USDT-SWAP",
            now - timedelta(seconds=10),
            perp=100.20,
            spot=100.0,
            funding_rate=0.0030,
        )
    ]

    rows = build_basis_arbitrage_rows(
        snapshots,
        now=now,
        min_abs_funding_rate=0.0001,
        min_abs_basis_pct=0.02,
        max_spread_pct=0.20,
        taker_fee_pct_per_leg=0.01,
    )

    assert rows[0].signal_ready is True
    assert rows[0].candidate_side == LONG_SPOT_SHORT_PERP
    assert rows[0].net_funding_8h_after_cost_pct is not None
    assert rows[0].net_funding_8h_after_cost_pct > 0


def test_build_basis_arbitrage_rows_explains_untradeable_costs_and_disagreement() -> None:
    now = datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc)
    rows = build_basis_arbitrage_rows(
        [
            _snapshot(
                "ETH-USDT-SWAP",
                now - timedelta(seconds=10),
                perp=99.9,
                spot=100.0,
                funding_rate=0.0002,
                perp_spread_pct=0.40,
            ),
        ],
        now=now,
        min_abs_funding_rate=0.0001,
        min_abs_basis_pct=0.02,
        max_spread_pct=0.20,
    )

    assert rows[0].signal_ready is False
    assert "spread too wide" in rows[0].reason
    assert "funding and basis disagree" in rows[0].reason


def test_build_basis_arbitrage_rows_supports_reverse_signal_label() -> None:
    now = datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc)
    rows = build_basis_arbitrage_rows(
        [_snapshot("SOL-USDT-SWAP", now, perp=99.5, spot=100.0, funding_rate=-0.0030)],
        now=now,
        taker_fee_pct_per_leg=0.01,
    )

    assert rows[0].candidate_side == LONG_PERP_SHORT_SPOT
