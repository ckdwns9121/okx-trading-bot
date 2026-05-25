from __future__ import annotations

import uuid
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

os.environ.setdefault("OKX_API_KEY", "dummy")
os.environ.setdefault("OKX_SECRET", "dummy")
os.environ.setdefault("OKX_PASSPHRASE", "dummy")

from app.db.database import Base
from app.models.research_market import BasisArbitrageSnapshot, PerpMarketSnapshot, ResearchEvent, ResearchEventOutcome


def test_research_market_models_insert_query_and_filter_quality_flags() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        PerpMarketSnapshot.__table__,
        BasisArbitrageSnapshot.__table__,
        ResearchEvent.__table__,
        ResearchEventOutcome.__table__,
    ])

    snapshot_id = uuid.uuid4()
    event_id = uuid.uuid4()
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        snapshot = PerpMarketSnapshot(
            id=snapshot_id,
            inst_id="BTC-USDT-SWAP",
            observed_at=observed_at,
            mid_price=100.0,
            last_price=100.0,
            spread_pct=0.01,
            bid_depth_notional=1000.0,
            ask_depth_notional=800.0,
            book_imbalance=0.111,
            reported_buy_notional=900.0,
            reported_sell_notional=100.0,
            reported_buy_count=9,
            reported_sell_count=1,
            funding_rate=0.0001,
            premium=0.0002,
            open_interest=10000.0,
            open_interest_usd=700000.0,
            data_quality_flags={"trade_side_semantics": "exchange_reported"},
            raw_json={"ticker": {"last": "100"}},
        )
        basis_snapshot = BasisArbitrageSnapshot(
            inst_id="BTC-USDT-SWAP",
            spot_inst_id="BTC-USDT",
            observed_at=observed_at,
            perp_mid_price=100.2,
            spot_mid_price=100.0,
            perp_last_price=100.2,
            spot_last_price=100.0,
            perp_spread_pct=0.01,
            spot_spread_pct=0.01,
            basis_pct=0.2,
            funding_rate=0.0002,
            estimated_daily_funding_pct=0.06,
            data_quality_flags={"strategy": "funding_basis_arbitrage"},
            raw_json={"funding": {"fundingRate": "0.0002"}},
        )
        event = ResearchEvent(
            id=event_id,
            event_type="crowded_perp_unwind",
            inst_id="BTC-USDT-SWAP",
            occurred_at=observed_at,
            candidate_side="short",
            snapshot_id=snapshot_id,
            crowding_score=0.7,
            features_json={"exchange_reported_trade_side_imbalance": 0.8},
        )
        outcome = ResearchEventOutcome(
            event_id=event_id,
            horizon_seconds=300,
            future_return_pct=0.2,
            cost_adjusted_edge_pct=0.17,
            max_adverse_excursion_pct=-0.01,
            max_favorable_excursion_pct=0.25,
            label=1,
            outcome_json={"fee_pct": 0.01},
        )
        session.add(snapshot)
        session.add(basis_snapshot)
        session.add(event)
        session.add(outcome)
        session.commit()

        stored = session.scalars(select(PerpMarketSnapshot).where(PerpMarketSnapshot.inst_id == "BTC-USDT-SWAP")).one()
        stored_basis = session.scalars(select(BasisArbitrageSnapshot).where(BasisArbitrageSnapshot.inst_id == "BTC-USDT-SWAP")).one()
        stored_event = session.scalars(select(ResearchEvent).where(ResearchEvent.snapshot_id == snapshot_id)).one()
        stored_outcome = session.scalars(select(ResearchEventOutcome).where(ResearchEventOutcome.event_id == event_id)).one()

    assert stored.data_quality_flags["trade_side_semantics"] == "exchange_reported"
    assert stored.raw_json["ticker"]["last"] == "100"
    assert stored_basis.spot_inst_id == "BTC-USDT"
    assert stored_basis.estimated_daily_funding_pct == 0.06
    assert stored_event.candidate_side == "short"
    assert stored_outcome.horizon_seconds == 300
    assert stored_outcome.label == 1
