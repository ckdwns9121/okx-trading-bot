from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Sequence

from app.core.funding_oi_reversion import (
    build_funding_oi_flush_events,
    label_funding_oi_flush_outcomes,
    summarize_funding_oi_flush_outcomes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run funding + OI flush mean-reversion event study.")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic snapshots and print a report.")
    parser.add_argument("--inst", default="", help="Comma-separated instrument filter for DB-backed runs.")
    parser.add_argument("--limit", type=int, default=100000, help="Maximum stored snapshots to load.")
    parser.add_argument("--lookback-seconds", type=int, default=300)
    parser.add_argument("--min-abs-move-pct", type=float, default=0.5)
    parser.add_argument("--min-abs-funding-rate", type=float, default=0.00005)
    parser.add_argument("--min-oi-change-pct", type=float, default=0.2)
    parser.add_argument("--cooldown-seconds", type=int, default=300)
    parser.add_argument("--entry-delay-seconds", type=int, default=20)
    parser.add_argument("--horizons", default="60,300,900", help="Comma-separated forward horizons in seconds.")
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.06)
    parser.add_argument("--mode", choices=("both", "long", "short"), default="both")
    parser.add_argument("--max-events-output", type=int, default=25)
    return parser


def synthetic_snapshots() -> list[dict[str, Any]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    for index in range(30):
        observed_at = start + timedelta(seconds=60 * index)
        if index < 5:
            price = 100.0
            oi = 1_000_000.0
        elif index < 10:
            price = 100.0 - (index - 4) * 0.4
            oi = 1_000_000.0 + (index - 4) * 3_000.0
        else:
            price = 98.0 + (index - 10) * 0.12
            oi = 1_018_000.0 - (index - 10) * 800.0
        rows.append(
            {
                "inst_id": "AI-USDT-SWAP",
                "observed_at": observed_at,
                "mid_price": price,
                "last_price": price,
                "spread_pct": 0.04,
                "bid_depth_notional": 10_000.0,
                "ask_depth_notional": 9_000.0,
                "book_imbalance": 0.0526,
                "reported_buy_notional": 2_000.0,
                "reported_sell_notional": 7_000.0,
                "funding_rate": 0.00008,
                "open_interest": oi / price,
                "open_interest_usd": oi,
            }
        )
    return rows


def run_event_study(
    snapshots: Sequence[dict[str, Any]],
    *,
    lookback_seconds: int,
    min_abs_move_pct: float,
    min_abs_funding_rate: float,
    min_oi_change_pct: float,
    cooldown_seconds: int,
    entry_delay_seconds: int,
    horizons_seconds: Sequence[int],
    round_trip_cost_pct: float,
    mode: str,
    max_events_output: int,
) -> dict[str, Any]:
    events = build_funding_oi_flush_events(
        snapshots,
        lookback_seconds=lookback_seconds,
        min_abs_move_pct=min_abs_move_pct,
        min_abs_funding_rate=min_abs_funding_rate,
        min_oi_change_pct=min_oi_change_pct,
        cooldown_seconds=cooldown_seconds,
        mode=mode,
    )
    outcomes_by_event = []
    event_rows = []
    for event in events:
        outcomes = label_funding_oi_flush_outcomes(
            event,
            snapshots,
            horizons_seconds=horizons_seconds,
            entry_delay_seconds=entry_delay_seconds,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        outcomes_by_event.append((event, outcomes))
        if len(event_rows) < max_events_output:
            event_rows.append(
                {
                    "inst_id": event.inst_id,
                    "occurred_at": event.occurred_at.isoformat(),
                    "candidate_side": event.candidate_side,
                    "score": event.score,
                    "features": asdict(event.features),
                    "outcomes": [_outcome_payload(outcome) for outcome in outcomes],
                }
            )

    return {
        "research_only": True,
        "parameters": {
            "lookback_seconds": lookback_seconds,
            "min_abs_move_pct": min_abs_move_pct,
            "min_abs_funding_rate": min_abs_funding_rate,
            "min_oi_change_pct": min_oi_change_pct,
            "cooldown_seconds": cooldown_seconds,
            "entry_delay_seconds": entry_delay_seconds,
            "horizons_seconds": list(horizons_seconds),
            "round_trip_cost_pct": round_trip_cost_pct,
            "mode": mode,
        },
        "event_count": len(events),
        "outcome_count": sum(len(outcomes) for _, outcomes in outcomes_by_event),
        "summary": summarize_funding_oi_flush_outcomes(events, outcomes_by_event),
        "events": event_rows,
        "truncated_event_output": len(events) > len(event_rows),
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
            "spread_pct": row.spread_pct,
            "bid_depth_notional": row.bid_depth_notional,
            "ask_depth_notional": row.ask_depth_notional,
            "book_imbalance": row.book_imbalance,
            "reported_buy_notional": row.reported_buy_notional,
            "reported_sell_notional": row.reported_sell_notional,
            "funding_rate": row.funding_rate,
            "open_interest": row.open_interest,
            "open_interest_usd": row.open_interest_usd,
        }
        for row in rows
    ]


def parse_horizons(raw: str) -> tuple[int, ...]:
    horizons = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not horizons:
        raise ValueError("at least one horizon is required")
    if any(horizon <= 0 for horizon in horizons):
        raise ValueError("horizons must be positive")
    return horizons


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    horizons = parse_horizons(args.horizons)
    if args.dry_run:
        snapshots = synthetic_snapshots()
    else:
        instruments = tuple(item.strip() for item in args.inst.split(",") if item.strip())
        snapshots = asyncio.run(load_snapshots_from_db(instruments=instruments, limit=args.limit))

    report = run_event_study(
        snapshots,
        lookback_seconds=args.lookback_seconds,
        min_abs_move_pct=args.min_abs_move_pct,
        min_abs_funding_rate=args.min_abs_funding_rate,
        min_oi_change_pct=args.min_oi_change_pct,
        cooldown_seconds=args.cooldown_seconds,
        entry_delay_seconds=args.entry_delay_seconds,
        horizons_seconds=horizons,
        round_trip_cost_pct=args.round_trip_cost_pct,
        mode=args.mode,
        max_events_output=args.max_events_output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _outcome_payload(outcome: Any) -> dict[str, Any]:
    payload = asdict(outcome)
    payload["entry_at"] = outcome.entry_at.isoformat()
    payload["exit_at"] = outcome.exit_at.isoformat()
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
