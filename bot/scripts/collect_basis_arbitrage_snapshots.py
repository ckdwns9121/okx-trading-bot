from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any, Sequence

from app.core.basis_arbitrage import basis_pct, estimated_daily_funding_pct, spot_inst_id_from_swap
from app.exchange.public_market_data import OKXPublicMarketData

DEFAULT_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")
MAX_INSTRUMENTS = 20
MAX_DURATION_SECONDS = 24 * 60 * 60
MAX_BOOK_DEPTH = 20
BACKOFF_SECONDS = 1.0


def parse_instruments(raw: str) -> tuple[str, ...]:
    instruments = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    if len(instruments) > MAX_INSTRUMENTS:
        raise ValueError(f"basis collector accepts at most {MAX_INSTRUMENTS} instruments")
    for inst_id in instruments:
        spot_inst_id_from_swap(inst_id)
    return instruments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect OKX spot/perp funding-basis arbitrage snapshots.")
    parser.add_argument("--inst", default=",".join(DEFAULT_INSTRUMENTS), help="Comma-separated OKX swap instrument IDs.")
    parser.add_argument("--interval", type=int, default=20, help="Polling interval in seconds.")
    parser.add_argument("--duration", type=int, default=1800, help="Run duration in seconds.")
    parser.add_argument("--depth", type=int, default=5, help=f"Order-book depth levels per side, capped at {MAX_BOOK_DEPTH}.")
    parser.add_argument("--dry-run", action="store_true", help="Collect one in-memory cycle and print JSON.")
    return parser


async def collect_one_basis_snapshot(
    client: OKXPublicMarketData,
    inst_id: str,
    *,
    depth: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    bounded_depth = max(1, min(int(depth), MAX_BOOK_DEPTH))
    spot_inst_id = spot_inst_id_from_swap(inst_id)
    flags: dict[str, Any] = {
        "strategy": "funding_basis_arbitrage",
        "spot_inst_id_derivation": "swap_suffix_removed",
        "dry_run_only": dry_run,
    }
    endpoint_errors: dict[str, str] = {}
    perp_ticker = await _fetch_with_gap_record(
        "perp_ticker",
        lambda: client.get_ticker(inst_id),
        errors=endpoint_errors,
        flags=flags,
    )
    spot_ticker = await _fetch_with_gap_record(
        "spot_ticker",
        lambda: client.get_ticker(spot_inst_id),
        errors=endpoint_errors,
        flags=flags,
    )
    perp_book = await _fetch_with_gap_record(
        "perp_book",
        lambda: client.get_order_book_top_depth(inst_id, depth=bounded_depth),
        errors=endpoint_errors,
        flags=flags,
    )
    spot_book = await _fetch_with_gap_record(
        "spot_book",
        lambda: client.get_order_book_top_depth(spot_inst_id, depth=bounded_depth),
        errors=endpoint_errors,
        flags=flags,
    )
    funding = await _fetch_with_gap_record(
        "funding",
        lambda: client.get_funding_rate(inst_id),
        errors=endpoint_errors,
        flags=flags,
    )
    perp_ticker = perp_ticker or {}
    spot_ticker = spot_ticker or {}
    perp_book = perp_book or {}
    spot_book = spot_book or {}
    funding = funding or {}
    perp_mid = float(perp_book.get("mid_price") or perp_ticker.get("mid_price") or 0.0)
    spot_mid = float(spot_book.get("mid_price") or spot_ticker.get("mid_price") or 0.0)
    funding_rate = _optional_float(funding.get("funding_rate"))

    return {
        "inst_id": inst_id,
        "spot_inst_id": spot_inst_id,
        "observed_at": observed_at.isoformat(),
        "perp_source_ts": perp_book.get("timestamp_iso") or perp_ticker.get("timestamp_iso"),
        "spot_source_ts": spot_book.get("timestamp_iso") or spot_ticker.get("timestamp_iso"),
        "funding_source_ts": funding.get("timestamp_iso") or funding.get("funding_time_iso"),
        "next_funding_time": funding.get("next_funding_time_iso"),
        "perp_mid_price": perp_mid,
        "spot_mid_price": spot_mid,
        "perp_last_price": float(perp_ticker.get("last") or 0.0),
        "spot_last_price": float(spot_ticker.get("last") or 0.0),
        "perp_spread_pct": float(perp_book.get("spread_pct") or perp_ticker.get("spread_pct") or 0.0),
        "spot_spread_pct": float(spot_book.get("spread_pct") or spot_ticker.get("spread_pct") or 0.0),
        "basis_pct": basis_pct(perp_mid_price=perp_mid, spot_mid_price=spot_mid),
        "funding_rate": funding_rate,
        "estimated_daily_funding_pct": estimated_daily_funding_pct(funding_rate),
        "data_quality_flags": flags,
        "raw_json": {
            "perp_ticker": _raw(perp_ticker),
            "spot_ticker": _raw(spot_ticker),
            "perp_book": _bounded_book_raw(perp_book.get("raw", {}), bounded_depth),
            "spot_book": _bounded_book_raw(spot_book.get("raw", {}), bounded_depth),
            "funding": _raw(funding),
            "endpoint_errors": endpoint_errors,
        },
    }


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.interval <= 0:
        raise ValueError("--interval must be positive")
    if args.duration <= 0:
        raise ValueError("--duration must be positive")
    if args.duration > MAX_DURATION_SECONDS:
        raise ValueError("basis collector duration is capped at 24 hours")

    instruments = parse_instruments(args.inst)
    client = OKXPublicMarketData()
    try:
        snapshots = [
            await collect_one_basis_snapshot(client, inst_id, depth=args.depth, dry_run=args.dry_run)
            for inst_id in instruments
        ]
        if args.dry_run:
            return snapshots

        await persist_snapshots(snapshots)
        elapsed = 0
        while elapsed + args.interval <= args.duration:
            await asyncio.sleep(args.interval)
            elapsed += args.interval
            next_batch = [
                await collect_one_basis_snapshot(client, inst_id, depth=args.depth, dry_run=False)
                for inst_id in instruments
            ]
            await persist_snapshots(next_batch)
            snapshots.extend(next_batch)
        return snapshots
    finally:
        await client.close()


async def persist_snapshots(snapshots: Sequence[dict[str, Any]]) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.research_market import BasisArbitrageSnapshot

    async with AsyncSessionLocal() as session:
        for snapshot in snapshots:
            session.add(
                BasisArbitrageSnapshot(
                    inst_id=snapshot["inst_id"],
                    spot_inst_id=snapshot["spot_inst_id"],
                    observed_at=_parse_optional_dt(snapshot["observed_at"]) or datetime.now(timezone.utc),
                    perp_source_ts=_parse_optional_dt(snapshot.get("perp_source_ts")),
                    spot_source_ts=_parse_optional_dt(snapshot.get("spot_source_ts")),
                    funding_source_ts=_parse_optional_dt(snapshot.get("funding_source_ts")),
                    next_funding_time=_parse_optional_dt(snapshot.get("next_funding_time")),
                    perp_mid_price=float(snapshot.get("perp_mid_price") or 0.0),
                    spot_mid_price=float(snapshot.get("spot_mid_price") or 0.0),
                    perp_last_price=float(snapshot.get("perp_last_price") or 0.0),
                    spot_last_price=float(snapshot.get("spot_last_price") or 0.0),
                    perp_spread_pct=float(snapshot.get("perp_spread_pct") or 0.0),
                    spot_spread_pct=float(snapshot.get("spot_spread_pct") or 0.0),
                    basis_pct=float(snapshot.get("basis_pct") or 0.0),
                    funding_rate=_optional_float(snapshot.get("funding_rate")),
                    estimated_daily_funding_pct=_optional_float(snapshot.get("estimated_daily_funding_pct")),
                    data_quality_flags=dict(snapshot.get("data_quality_flags") or {}),
                    raw_json=dict(snapshot.get("raw_json") or {}),
                )
            )
        await session.commit()


def _parse_optional_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


async def _fetch_with_gap_record(
    endpoint: str,
    fetcher: Callable[[], Awaitable[Any]],
    *,
    errors: dict[str, str],
    flags: dict[str, Any],
) -> Any:
    try:
        return await fetcher()
    except Exception as exc:
        errors[endpoint] = str(exc)
        flags.setdefault("endpoint_gaps", []).append(endpoint)
        flags["backoff_seconds"] = BACKOFF_SECONDS
        await asyncio.sleep(BACKOFF_SECONDS)
        return None


def _raw(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw")
    return raw if isinstance(raw, dict) else {}


def _bounded_book_raw(raw: Any, depth: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "ts": raw.get("ts"),
        "seqId": raw.get("seqId"),
        "bids": list(raw.get("bids", []))[:depth],
        "asks": list(raw.get("asks", []))[:depth],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    snapshots = asyncio.run(run(args))
    print(json.dumps({"count": len(snapshots), "snapshots": snapshots}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
