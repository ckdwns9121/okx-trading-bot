from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any, Sequence

from app.exchange.public_market_data import OKXPublicMarketData

DEFAULT_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")
MAX_DEFAULT_INSTRUMENTS = 3
MAX_DURATION_SECONDS = 24 * 60 * 60
MAX_BOOK_DEPTH = 20
MAX_RAW_TRADES = 20
BACKOFF_SECONDS = 1.0


def book_imbalance(bid_depth_notional: float, ask_depth_notional: float) -> float:
    total = float(bid_depth_notional) + float(ask_depth_notional)
    if total <= 0.0:
        return 0.0
    return (float(bid_depth_notional) - float(ask_depth_notional)) / total


def parse_instruments(raw: str) -> tuple[str, ...]:
    instruments = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    if len(instruments) > MAX_DEFAULT_INSTRUMENTS:
        raise ValueError("v1 collector accepts at most three instruments")
    return instruments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect OKX public snapshots for crowded-perp unwind research.")
    parser.add_argument("--inst", default=",".join(DEFAULT_INSTRUMENTS), help="Comma-separated OKX instrument IDs.")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds.")
    parser.add_argument("--duration", type=int, default=1800, help="Run duration in seconds.")
    parser.add_argument("--depth", type=int, default=5, help=f"Order-book depth levels per side, capped at {MAX_BOOK_DEPTH}.")
    parser.add_argument("--dry-run", action="store_true", help="Collect one in-memory cycle and print JSON.")
    return parser


async def collect_one_snapshot(
    client: OKXPublicMarketData,
    inst_id: str,
    *,
    depth: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    bounded_depth = _bounded_depth(depth)
    data_quality_flags: dict[str, Any] = {
        "trade_side_semantics": "exchange_reported",
        "dry_run_only": dry_run,
    }
    endpoint_errors: dict[str, str] = {}
    ticker = await _fetch_with_gap_record(
        "ticker",
        lambda: client.get_ticker(inst_id),
        errors=endpoint_errors,
        flags=data_quality_flags,
    )
    book = await _fetch_with_gap_record(
        "book",
        lambda: client.get_order_book_top_depth(inst_id, depth=bounded_depth),
        errors=endpoint_errors,
        flags=data_quality_flags,
    )
    trades = await _fetch_with_gap_record(
        "trades",
        lambda: client.get_recent_trades(inst_id, limit=100),
        errors=endpoint_errors,
        flags=data_quality_flags,
    )
    funding = await _fetch_with_gap_record(
        "funding",
        lambda: client.get_funding_rate(inst_id),
        errors=endpoint_errors,
        flags=data_quality_flags,
    )
    open_interest = await _fetch_with_gap_record(
        "open_interest",
        lambda: client.get_open_interest(inst_id),
        errors=endpoint_errors,
        flags=data_quality_flags,
    )
    ticker = ticker or {}
    book = book or {}
    trades = trades or []
    funding = funding or {}
    open_interest = open_interest or {}
    buy_trades = [trade for trade in trades if trade["side"] == "buy"]
    sell_trades = [trade for trade in trades if trade["side"] == "sell"]
    reported_buy_notional = sum(float(trade["notional"]) for trade in buy_trades)
    reported_sell_notional = sum(float(trade["notional"]) for trade in sell_trades)
    bid_depth = float(book.get("bid_depth_notional") or 0.0)
    ask_depth = float(book.get("ask_depth_notional") or 0.0)

    return {
        "inst_id": inst_id,
        "observed_at": observed_at.isoformat(),
        "ticker_source_ts": ticker.get("timestamp_iso"),
        "book_source_ts": book.get("timestamp_iso"),
        "trades_source_ts": max((trade.get("timestamp_iso") for trade in trades if trade.get("timestamp_iso")), default=None),
        "funding_source_ts": funding.get("timestamp_iso") or funding.get("funding_time_iso"),
        "oi_source_ts": open_interest.get("timestamp_iso"),
        "mid_price": book.get("mid_price") or ticker.get("mid_price"),
        "last_price": ticker.get("last"),
        "spread_pct": book.get("spread_pct"),
        "bid_depth_notional": bid_depth,
        "ask_depth_notional": ask_depth,
        "book_imbalance": book_imbalance(bid_depth, ask_depth),
        "reported_buy_notional": reported_buy_notional,
        "reported_sell_notional": reported_sell_notional,
        "reported_buy_count": len(buy_trades),
        "reported_sell_count": len(sell_trades),
        "funding_rate": funding.get("funding_rate"),
        "premium": funding.get("premium"),
        "open_interest": open_interest.get("open_interest"),
        "open_interest_usd": open_interest.get("open_interest_usd"),
        "data_quality_flags": data_quality_flags,
        "raw_json": {
            "ticker": _without_normalized_raw(ticker),
            "book": _bounded_book_raw(book.get("raw", {}), bounded_depth),
            "trades": [trade.get("raw", {}) for trade in trades[:MAX_RAW_TRADES]],
            "funding": funding.get("raw", {}),
            "open_interest": open_interest.get("raw", {}),
            "endpoint_errors": endpoint_errors,
        },
    }


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.interval <= 0:
        raise ValueError("--interval must be positive")
    if args.duration <= 0:
        raise ValueError("--duration must be positive")
    if args.duration > MAX_DURATION_SECONDS:
        raise ValueError("v1 collector duration is capped at 24 hours")

    instruments = parse_instruments(args.inst)
    client = OKXPublicMarketData()
    try:
        snapshots = [
            await collect_one_snapshot(client, inst_id, depth=args.depth, dry_run=args.dry_run)
            for inst_id in instruments
        ]
        if args.dry_run:
            return snapshots

        await persist_snapshots(snapshots)
        elapsed = 0
        while elapsed + args.interval <= args.duration:
            await asyncio.sleep(args.interval)
            elapsed += args.interval
            next_batch = [await collect_one_snapshot(client, inst_id, depth=args.depth, dry_run=False) for inst_id in instruments]
            await persist_snapshots(next_batch)
            snapshots.extend(next_batch)
        return snapshots
    finally:
        await client.close()


async def persist_snapshots(snapshots: Sequence[dict[str, Any]]) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.research_market import PerpMarketSnapshot

    async with AsyncSessionLocal() as session:
        for snapshot in snapshots:
            session.add(
                PerpMarketSnapshot(
                    inst_id=snapshot["inst_id"],
                    observed_at=_parse_optional_dt(snapshot["observed_at"]) or datetime.now(timezone.utc),
                    ticker_source_ts=_parse_optional_dt(snapshot.get("ticker_source_ts")),
                    book_source_ts=_parse_optional_dt(snapshot.get("book_source_ts")),
                    trades_source_ts=_parse_optional_dt(snapshot.get("trades_source_ts")),
                    funding_source_ts=_parse_optional_dt(snapshot.get("funding_source_ts")),
                    oi_source_ts=_parse_optional_dt(snapshot.get("oi_source_ts")),
                    mid_price=float(snapshot.get("mid_price") or 0.0),
                    last_price=float(snapshot.get("last_price") or 0.0),
                    spread_pct=float(snapshot.get("spread_pct") or 0.0),
                    bid_depth_notional=float(snapshot.get("bid_depth_notional") or 0.0),
                    ask_depth_notional=float(snapshot.get("ask_depth_notional") or 0.0),
                    book_imbalance=float(snapshot.get("book_imbalance") or 0.0),
                    reported_buy_notional=float(snapshot.get("reported_buy_notional") or 0.0),
                    reported_sell_notional=float(snapshot.get("reported_sell_notional") or 0.0),
                    reported_buy_count=int(snapshot.get("reported_buy_count") or 0),
                    reported_sell_count=int(snapshot.get("reported_sell_count") or 0),
                    funding_rate=_optional_float(snapshot.get("funding_rate")),
                    premium=_optional_float(snapshot.get("premium")),
                    open_interest=_optional_float(snapshot.get("open_interest")),
                    open_interest_usd=_optional_float(snapshot.get("open_interest_usd")),
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


def _bounded_depth(depth: int) -> int:
    return max(1, min(int(depth), MAX_BOOK_DEPTH))


def _without_normalized_raw(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw")
    if isinstance(raw, dict):
        return raw
    return {}


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
