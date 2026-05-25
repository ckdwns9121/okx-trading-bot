from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from app.core.crowded_unwind_research import (
    build_event_candidates,
    label_event_outcomes,
    promotion_gate_report,
    summarize_outcomes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run crowded-perp unwind event-study research.")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic snapshots and print a report.")
    parser.add_argument("--inst", default="", help="Comma-separated instrument filter for DB-backed runs; empty loads all instruments and evaluates each independently.")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum stored snapshots to load.")
    parser.add_argument("--lookback", type=int, default=12, help="Snapshot lookback window for event creation.")
    parser.add_argument("--min-crowding-score", type=float, default=0.35)
    parser.add_argument("--persist-events", action="store_true", help="Persist derived research events and outcomes.")
    return parser


def synthetic_snapshots() -> list[dict[str, Any]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    for index in range(20):
        rows.append(
            {
                "inst_id": "BTC-USDT-SWAP",
                "observed_at": start + timedelta(seconds=60 * index),
                "mid_price": 100.0 + min(index, 11) * 0.01 - max(index - 11, 0) * 0.18,
                "last_price": 100.0 + min(index, 11) * 0.01 - max(index - 11, 0) * 0.18,
                "bid_depth_notional": 9000.0 - index * 120.0,
                "ask_depth_notional": 5000.0 - index * 40.0,
                "reported_buy_notional": 8000.0 + index * 50.0,
                "reported_sell_notional": 2000.0,
                "funding_rate": 0.0001 + index * 0.00001,
                "open_interest": 100000.0 + index * 1000.0,
            }
        )
    return rows


def run_event_study(
    snapshots: Sequence[dict[str, Any]],
    *,
    min_crowding_score: float,
    lookback: int = 12,
) -> dict[str, Any]:
    events = build_event_candidates(snapshots, min_crowding_score=min_crowding_score, lookback=lookback)
    event_rows = []
    outcomes = []
    for event in events:
        event_outcomes = label_event_outcomes(event, snapshots)
        outcomes.extend(event_outcomes)
        event_rows.append(
            {
                "inst_id": event.inst_id,
                "occurred_at": event.occurred_at.isoformat(),
                "candidate_side": event.candidate_side,
                "crowding_score": event.crowding_score,
                "features": asdict(event.features),
                "outcomes": [asdict(outcome) for outcome in event_outcomes],
            }
        )
    summary = summarize_outcomes(outcomes)
    promotion = promotion_gate_report(
        total_events=len(events),
        oos_fold_event_counts=[len(events)],
        net_expectancy_pct=float(summary["net_expectancy_pct"]),
        bootstrap_lower_bound_pct=0.0,
        robust_instrument_count=1,
        robust_adjacent_horizon_count=1,
        worst_oos_expectancy_pct=float(summary["worst_edge_pct"]),
        phase_1a_quality_passed=False,
    )
    return {
        "event_count": len(events),
        "outcome_count": len(outcomes),
        "summary": summary,
        "promotion_gate": promotion,
        "research_only": True,
        "events": event_rows,
    }


async def load_snapshots_from_db(*, instruments: Sequence[str], limit: int) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.models.research_market import PerpMarketSnapshot

    stmt = select(PerpMarketSnapshot).order_by(PerpMarketSnapshot.observed_at).limit(max(1, limit))
    if instruments:
        stmt = stmt.where(PerpMarketSnapshot.inst_id.in_(tuple(instruments)))

    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(stmt)).all()

    return [
        {
            "snapshot_id": row.id,
            "inst_id": row.inst_id,
            "observed_at": row.observed_at,
            "mid_price": row.mid_price,
            "last_price": row.last_price,
            "bid_depth_notional": row.bid_depth_notional,
            "ask_depth_notional": row.ask_depth_notional,
            "reported_buy_notional": row.reported_buy_notional,
            "reported_sell_notional": row.reported_sell_notional,
            "funding_rate": row.funding_rate,
            "open_interest": row.open_interest,
        }
        for row in rows
    ]


async def persist_event_study(report: dict[str, Any], snapshots: Sequence[dict[str, Any]]) -> int:
    from app.db.database import AsyncSessionLocal
    from app.models.research_market import ResearchEvent, ResearchEventOutcome

    snapshot_by_key = {
        (snapshot["inst_id"], snapshot["observed_at"]): snapshot.get("snapshot_id")
        for snapshot in snapshots
    }
    async with AsyncSessionLocal() as session:
        created = 0
        for event_payload in report["events"]:
            occurred_at = datetime.fromisoformat(event_payload["occurred_at"])
            event = ResearchEvent(
                event_type="crowded_perp_unwind",
                inst_id=event_payload["inst_id"],
                occurred_at=occurred_at,
                candidate_side=event_payload["candidate_side"],
                snapshot_id=snapshot_by_key.get((event_payload["inst_id"], occurred_at)),
                crowding_score=float(event_payload["crowding_score"]),
                features_json=event_payload["features"],
            )
            session.add(event)
            await session.flush()
            for outcome in event_payload["outcomes"]:
                session.add(
                    ResearchEventOutcome(
                        event_id=event.id,
                        horizon_seconds=outcome["horizon_seconds"],
                        future_return_pct=outcome["future_return_pct"],
                        cost_adjusted_edge_pct=outcome["cost_adjusted_edge_pct"],
                        max_adverse_excursion_pct=outcome["max_adverse_excursion_pct"],
                        max_favorable_excursion_pct=outcome["max_favorable_excursion_pct"],
                        label=outcome["label"],
                        outcome_json={"source": "crowded_unwind_event_study"},
                    )
                )
            created += 1
        await session.commit()
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dry_run:
        snapshots = synthetic_snapshots()
        report = run_event_study(snapshots, min_crowding_score=args.min_crowding_score, lookback=6)
    else:
        instruments = tuple(item.strip() for item in args.inst.split(",") if item.strip())
        snapshots = asyncio.run(load_snapshots_from_db(instruments=instruments, limit=args.limit))
        report = run_event_study(snapshots, min_crowding_score=args.min_crowding_score, lookback=args.lookback)
        if args.persist_events:
            report["persisted_event_count"] = asyncio.run(persist_event_study(report, snapshots))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
