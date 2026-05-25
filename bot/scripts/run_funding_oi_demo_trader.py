from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import httpx

from app.core.funding_oi_reversion import build_funding_oi_flush_events
from app.exchange.okx_client import OKXClient

STRATEGY_NAME = "Funding + OI Flush Reversal"
LONG_POS_SIDE = "long"
_DEMO_TELEGRAM_NOTIFIER: Any | None = None
_TELEGRAM_EVENT_LABELS = {
    "funding_oi_demo_started": "데모 트레이더 시작",
    "funding_oi_demo_stopped": "데모 트레이더 중지",
    "funding_oi_signal": "롱 신호 감지",
    "funding_oi_position_opened": "포지션 진입",
    "funding_oi_position_partially_closed": "포지션 일부 청산",
    "funding_oi_position_closed": "포지션 청산",
    "funding_oi_position_reconciled": "포지션 동기화",
    "funding_oi_order_error": "주문 실패",
    "funding_oi_close_error": "청산 실패",
    "funding_oi_price_mismatch": "가격 괴리 차단",
    "funding_oi_price_check_error": "가격 확인 실패",
    "funding_oi_reconciliation_error": "포지션 동기화 실패",
}


class OrderNotFilledError(RuntimeError):
    """Raised when OKX accepts an order request but the order never fills."""


class PositionAlreadyFlatError(RuntimeError):
    """Raised when OKX reports there is no matching position to close."""


class ExecutionPriceMismatchError(RuntimeError):
    """Raised when the signal feed price does not match the executable OKX price."""


@dataclass(frozen=True)
class InstrumentSpec:
    inst_id: str
    ct_val: Decimal
    lot_size: Decimal
    min_size: Decimal
    max_market_size: Decimal | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run funding/OI flush reversal on OKX demo trading.")
    parser.add_argument("--pairs", default="", help="Comma-separated instruments. Empty uses recently collected instruments.")
    parser.add_argument("--margin-usd", type=float, default=5000.0)
    parser.add_argument("--leverage", type=int, default=5)
    parser.add_argument("--duration-seconds", type=int, default=4 * 60 * 60)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--history-seconds", type=int, default=1800)
    parser.add_argument("--fresh-seconds", type=int, default=120)
    parser.add_argument("--lookback-seconds", type=int, default=300)
    parser.add_argument("--min-abs-move-pct", type=float, default=0.5)
    parser.add_argument("--min-abs-funding-rate", type=float, default=0.00005)
    parser.add_argument("--min-oi-change-pct", type=float, default=0.2)
    parser.add_argument("--cooldown-seconds", type=int, default=300)
    parser.add_argument("--hold-seconds", type=int, default=900)
    parser.add_argument("--hard-stop-pct", type=float, default=1.2, help="Price move against entry that closes early.")
    parser.add_argument("--take-profit-pct", type=float, default=2.0, help="Price move in favor that closes the position.")
    parser.add_argument("--trailing-activation-pct", type=float, default=1.0, help="Profit threshold that arms the trailing stop.")
    parser.add_argument("--trailing-drawdown-pct", type=float, default=0.5, help="Pullback from peak profit that closes the position.")
    parser.add_argument("--exit-cooldown-seconds", type=int, default=300, help="Do not re-enter the same instrument after an exit.")
    parser.add_argument(
        "--max-execution-price-deviation-pct",
        type=float,
        default=2.0,
        help="Skip new entries when OKX executable price differs from the snapshot price by more than this. Use 0 to disable.",
    )
    parser.add_argument("--max-margin-utilization", type=float, default=0.90)
    parser.add_argument("--max-market-size-fraction", type=float, default=0.50)
    parser.add_argument(
        "--validate-demo-instruments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pre-filter instruments that the OKX demo trading API rejects.",
    )
    parser.add_argument("--status-event-seconds", type=int, default=30)
    parser.add_argument("--state-file", default=".omx/state/funding_oi_demo_trader.json")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate signals without sending demo orders.")
    return parser


async def load_recent_snapshots(*, instruments: Sequence[str], history_seconds: int) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.models.research_market import PerpMarketSnapshot

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=history_seconds)
    stmt = (
        select(PerpMarketSnapshot)
        .where(PerpMarketSnapshot.observed_at >= cutoff)
        .order_by(PerpMarketSnapshot.observed_at.asc())
    )
    if instruments:
        stmt = stmt.where(PerpMarketSnapshot.inst_id.in_(tuple(instruments)))

    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(stmt)).all()

    return [_snapshot_payload(row) for row in rows]


async def load_recent_instruments(*, fresh_seconds: int) -> tuple[str, ...]:
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.models.research_market import PerpMarketSnapshot

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=fresh_seconds)
    stmt = (
        select(PerpMarketSnapshot.inst_id)
        .where(PerpMarketSnapshot.observed_at >= cutoff)
        .distinct()
        .order_by(PerpMarketSnapshot.inst_id.asc())
    )
    async with AsyncSessionLocal() as session:
        return tuple((await session.scalars(stmt)).all())


async def fetch_instrument_specs(instruments: Sequence[str]) -> dict[str, InstrumentSpec]:
    if not instruments:
        return {}
    async with httpx.AsyncClient(base_url="https://www.okx.com", timeout=10.0) as client:
        response = await client.get("/api/v5/public/instruments", params={"instType": "SWAP"})
        response.raise_for_status()
    payload = response.json()
    if str(payload.get("code", "0")) != "0":
        raise RuntimeError(f"OKX instruments error: {payload}")

    wanted = set(instruments)
    specs: dict[str, InstrumentSpec] = {}
    for row in payload.get("data", []):
        inst_id = row.get("instId")
        if inst_id not in wanted:
            continue
        specs[inst_id] = InstrumentSpec(
            inst_id=inst_id,
            ct_val=_positive_decimal(row.get("ctVal"), default="1"),
            lot_size=_positive_decimal(row.get("lotSz"), default="1"),
            min_size=_positive_decimal(row.get("minSz"), default="1"),
            max_market_size=_optional_positive_decimal(row.get("maxMktSz")),
        )
    missing = sorted(wanted.difference(specs))
    if missing:
        raise RuntimeError(f"Missing OKX instrument specs: {missing}")
    return specs


async def get_usdt_available(client: OKXClient) -> float:
    balance = await client.get_account_balance()
    for account in balance.get("data", []):
        for detail in account.get("details", []):
            if detail.get("ccy") == "USDT":
                return float(detail.get("availBal") or detail.get("cashBal") or detail.get("eq") or 0.0)
    return 0.0


async def reconcile_state_with_exchange(
    client: OKXClient,
    *,
    state: dict[str, Any],
    instruments: Sequence[str],
    specs: Mapping[str, InstrumentSpec],
    leverage: int,
) -> list[dict[str, Any]]:
    positions = await client.get_positions()
    exchange_by_inst = {
        str(row.get("instId")): row
        for row in positions
        if str(row.get("instId")) in set(instruments)
        and str(row.get("posSide") or LONG_POS_SIDE) in (LONG_POS_SIDE, "net")
        and _positive_position_size(row) > 0
    }
    items: list[dict[str, Any]] = []

    local_position = state.get("open_position")
    if isinstance(local_position, dict):
        inst_id = str(local_position["inst_id"])
        exchange_position = exchange_by_inst.get(inst_id)
        if exchange_position is None:
            items.append(
                mark_position_exchange_flat(
                    state,
                    position=local_position,
                    reason="OKX reports no matching open position",
                )
            )
            return items

        exchange_size = _positive_position_size(exchange_position)
        local_size = Decimal(str(local_position.get("size") or "0"))
        if exchange_size != local_size:
            local_position["size"] = _decimal_to_okx_size(exchange_size)
            avg_px = _optional_decimal(exchange_position.get("avgPx"))
            if avg_px is not None and avg_px > 0:
                local_position["entry_price"] = float(avg_px)
            spec = specs.get(inst_id)
            if spec is not None:
                local_position["notional_usd"] = float(
                    exchange_size
                    * spec.ct_val
                    * Decimal(str(local_position.get("entry_price") or 0))
                )
            items.append(
                {
                    "type": "size_sync",
                    "inst_id": inst_id,
                    "message": f"Synced {inst_id} local size from {local_size} to OKX size {exchange_size}",
                    "previous_size": _decimal_to_okx_size(local_size),
                    "exchange_size": _decimal_to_okx_size(exchange_size),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
        state["open_position"] = local_position
        return items

    if exchange_by_inst:
        inst_id, exchange_position = sorted(exchange_by_inst.items())[0]
        exchange_size = _positive_position_size(exchange_position)
        avg_px = _optional_decimal(exchange_position.get("avgPx")) or Decimal(str(exchange_position.get("last") or "0"))
        spec = specs.get(inst_id)
        ct_val = spec.ct_val if spec is not None else Decimal("1")
        now = datetime.now(timezone.utc).isoformat()
        adopted = {
            "inst_id": inst_id,
            "side": LONG_POS_SIDE,
            "event_key": f"exchange_adopted:{now}",
            "event_at": now,
            "opened_at": now,
            "entry_price": float(avg_px),
            "size": _decimal_to_okx_size(exchange_size),
            "ct_val": str(ct_val),
            "notional_usd": float(exchange_size * ct_val * avg_px),
            "margin_usd": None,
            "leverage": int(exchange_position.get("lever") or leverage),
            "peak_price": float(avg_px),
            "peak_move_pct": 0.0,
            "features": {"setup": "exchange_adopted"},
            "open_result": {"source": "exchange_reconciliation"},
        }
        state["open_position"] = adopted
        item = {
            "type": "adopt_exchange_position",
            "inst_id": inst_id,
            "message": f"Adopted existing OKX {inst_id} position into trader state",
            "exchange_size": _decimal_to_okx_size(exchange_size),
            "at": now,
        }
        state.setdefault("reconciliations", []).append(item)
        items.append(item)

    return items


async def _reconcile_and_record(
    client: OKXClient,
    *,
    state: dict[str, Any],
    instruments: Sequence[str],
    specs: Mapping[str, InstrumentSpec],
    leverage: int,
    state_path: Path,
) -> None:
    try:
        reconciled = await reconcile_state_with_exchange(
            client,
            state=state,
            instruments=instruments,
            specs=specs,
            leverage=leverage,
        )
    except Exception as exc:
        item = {
            "type": "reconciliation_error",
            "message": str(exc),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        state.setdefault("reconciliation_errors", []).append(item)
        _save_state(state_path, state)
        await _record_demo_event(
            "funding_oi_reconciliation_error",
            level="error",
            message=str(exc),
            state=state,
            details={"reconciliation_error": item},
        )
        return

    for item in reconciled:
        await _record_demo_event(
            "funding_oi_position_reconciled",
            level="warning",
            message=item["message"],
            pair=item.get("inst_id"),
            state=state,
            details={"reconciliation": item},
        )


def mark_position_exchange_flat(
    state: dict[str, Any],
    *,
    position: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    inst_id = str(position["inst_id"])
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "type": "exchange_flat",
        "inst_id": inst_id,
        "message": f"Cleared local {inst_id} position because OKX is flat",
        "reason": reason,
        "local_position": _public_position(position),
        "at": now,
    }
    state["open_position"] = None
    state.setdefault("last_exit_by_instrument", {})[inst_id] = now
    state.setdefault("reconciliations", []).append(item)
    return item


async def filter_demo_tradeable_instruments(
    client: OKXClient,
    *,
    instruments: Sequence[str],
    leverage: int,
) -> tuple[tuple[str, ...], dict[str, str]]:
    valid: list[str] = []
    blocked: dict[str, str] = {}
    for inst_id in instruments:
        try:
            await client.set_leverage(inst_id, leverage)
            valid.append(inst_id)
        except Exception as exc:
            message = str(exc)
            if _is_unknown_instrument_error(message):
                blocked[inst_id] = message
                continue
            # Keep temporarily failing instruments in the universe; order-time
            # handling will record the exact failure if a signal appears.
            valid.append(inst_id)
            if "429" in message or "too many requests" in message.lower():
                await asyncio.sleep(1.0)
                continue
        await asyncio.sleep(0.25)
    return tuple(valid), blocked


async def fetch_execution_ticker(client: OKXClient, pair: str) -> dict[str, Any]:
    result = await client._request("GET", "/api/v5/market/ticker", params={"instId": pair})
    rows = result.get("data", [])
    if not rows:
        raise RuntimeError(f"OKX executable ticker is empty for {pair}")
    row = rows[0]
    bid = _optional_decimal(row.get("bidPx")) or Decimal("0")
    ask = _optional_decimal(row.get("askPx")) or Decimal("0")
    last = _optional_decimal(row.get("last")) or Decimal("0")
    mid = ((bid + ask) / Decimal("2")) if bid > 0 and ask > 0 else last
    if mid <= 0:
        raise RuntimeError(f"OKX executable ticker has no usable price for {pair}: {row}")
    return {
        "inst_id": row.get("instId", pair),
        "mid_price": float(mid),
        "last_price": float(last),
        "bid": float(bid),
        "ask": float(ask),
        "timestamp": row.get("ts"),
        "raw": dict(row),
    }


def ensure_execution_price_aligned(
    *,
    pair: str,
    snapshot_price: float,
    execution_price: float,
    max_deviation_pct: float,
) -> float:
    deviation = _price_deviation_pct(snapshot_price, execution_price)
    if max_deviation_pct > 0.0 and deviation > max_deviation_pct:
        raise ExecutionPriceMismatchError(
            f"{pair} executable price deviates from snapshot by {deviation:.2f}% "
            f"(snapshot={snapshot_price}, executable={execution_price}, limit={max_deviation_pct}%)"
        )
    return deviation


def _price_deviation_pct(reference_price: float, observed_price: float) -> float:
    if reference_price <= 0.0 or observed_price <= 0.0:
        return float("inf")
    return abs((observed_price / reference_price) - 1.0) * 100.0


def choose_fresh_event(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    processed_events: set[str],
    fresh_seconds: int,
    lookback_seconds: int,
    min_abs_move_pct: float,
    min_abs_funding_rate: float,
    min_oi_change_pct: float,
    cooldown_seconds: int,
    blocked_instruments: set[str] | None = None,
    last_exit_by_instrument: Mapping[str, str] | None = None,
    exit_cooldown_seconds: int = 0,
) -> Any | None:
    now = datetime.now(timezone.utc)
    events = build_funding_oi_flush_events(
        snapshots,
        lookback_seconds=lookback_seconds,
        min_abs_move_pct=min_abs_move_pct,
        min_abs_funding_rate=min_abs_funding_rate,
        min_oi_change_pct=min_oi_change_pct,
        cooldown_seconds=cooldown_seconds,
        mode="long",
    )
    candidates = []
    blocked = blocked_instruments or set()
    recent_exit_cutoff = now - timedelta(seconds=max(0, int(exit_cooldown_seconds)))
    for event in events:
        event_key = _event_key(event.inst_id, event.occurred_at)
        event_age = (now - event.occurred_at).total_seconds()
        if event.inst_id in blocked or event_key in processed_events or event_age < 0 or event_age > fresh_seconds:
            continue
        last_exit_raw = (last_exit_by_instrument or {}).get(event.inst_id)
        if last_exit_raw:
            try:
                if datetime.fromisoformat(last_exit_raw) >= recent_exit_cutoff:
                    continue
            except ValueError:
                pass
        candidates.append(event)
    if not candidates:
        return None
    return max(candidates, key=lambda event: (event.score, event.occurred_at))


def calculate_order_size(*, notional_usd: float, price: float, spec: InstrumentSpec) -> Decimal:
    return calculate_order_size_with_market_cap(
        notional_usd=notional_usd,
        price=price,
        spec=spec,
        max_market_size_fraction=1.0,
    )


def calculate_order_size_with_market_cap(
    *,
    notional_usd: float,
    price: float,
    spec: InstrumentSpec,
    max_market_size_fraction: float,
) -> Decimal:
    if notional_usd <= 0.0:
        raise ValueError("notional_usd must be positive")
    if price <= 0.0:
        raise ValueError("price must be positive")
    if max_market_size_fraction <= 0.0 or max_market_size_fraction > 1.0:
        raise ValueError("max_market_size_fraction must be in (0, 1]")
    raw_size = Decimal(str(notional_usd)) / (Decimal(str(price)) * spec.ct_val)
    stepped = (raw_size / spec.lot_size).to_integral_value(rounding=ROUND_DOWN) * spec.lot_size
    if spec.max_market_size is not None:
        max_size = spec.max_market_size * Decimal(str(max_market_size_fraction))
        max_stepped = (max_size / spec.lot_size).to_integral_value(rounding=ROUND_DOWN) * spec.lot_size
        stepped = min(stepped, max_stepped)
    if stepped < spec.min_size:
        raise ValueError(f"calculated size {stepped} is below min size {spec.min_size} for {spec.inst_id}")
    return stepped


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from app.config import settings

    if settings.OKX_MODE != "demo":
        raise RuntimeError(f"Refusing to trade: OKX_MODE={settings.OKX_MODE!r}, expected 'demo'")
    if args.leverage <= 0:
        raise ValueError("--leverage must be positive")
    if args.margin_usd <= 0:
        raise ValueError("--margin-usd must be positive")
    if args.max_margin_utilization <= 0.0 or args.max_margin_utilization > 1.0:
        raise ValueError("--max-margin-utilization must be in (0, 1]")

    state_path = Path(args.state_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = _load_state(state_path)
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("processed_events", [])
    state.setdefault("closed_trades", [])
    state.setdefault("open_position", None)
    state.setdefault("blocked_instruments", {})
    state.setdefault("last_exit_by_instrument", {})
    state.setdefault("close_errors", [])
    state.setdefault("reconciliations", [])
    state.setdefault("reconciliation_errors", [])
    state["mode"] = settings.OKX_MODE
    state["dry_run"] = bool(args.dry_run)
    state["strategy_name"] = STRATEGY_NAME
    telegram_notifier = _build_demo_telegram_notifier(settings)
    _set_demo_telegram_notifier(telegram_notifier)

    explicit_pairs = tuple(item.strip() for item in args.pairs.split(",") if item.strip())
    instruments = explicit_pairs or await load_recent_instruments(fresh_seconds=args.fresh_seconds)
    if not instruments:
        raise RuntimeError("No recently collected instruments found")
    specs = await fetch_instrument_specs(instruments)

    client = OKXClient(settings.OKX_API_KEY, settings.OKX_SECRET, settings.OKX_PASSPHRASE, settings.OKX_MODE)
    opened = 0
    closed = 0
    loops = 0
    started_at = datetime.now(timezone.utc)
    stop_at = started_at + timedelta(seconds=args.duration_seconds)
    try:
        if not args.dry_run and args.validate_demo_instruments:
            valid_instruments, blocked = await filter_demo_tradeable_instruments(
                client,
                instruments=instruments,
                leverage=int(args.leverage),
            )
            state["blocked_instruments"] = {
                **dict(state.get("blocked_instruments") or {}),
                **blocked,
            }
            instruments = valid_instruments
            specs = {inst_id: spec for inst_id, spec in specs.items() if inst_id in set(instruments)}
            if not instruments:
                raise RuntimeError("No instruments accepted by the OKX demo trading API")

        available_usdt = await get_usdt_available(client)
        effective_margin = min(float(args.margin_usd), available_usdt * float(args.max_margin_utilization))
        if effective_margin <= 0.0:
            raise RuntimeError("No usable USDT balance available in OKX demo account")
        if effective_margin < float(args.margin_usd):
            state["margin_capped"] = {
                "requested_margin_usd": float(args.margin_usd),
                "available_usdt": available_usdt,
                "max_margin_utilization": float(args.max_margin_utilization),
                "effective_margin_usd": effective_margin,
            }

        state["config"] = {
            "instruments": list(instruments),
            "requested_margin_usd": float(args.margin_usd),
            "effective_margin_usd": effective_margin,
            "leverage": int(args.leverage),
            "notional_usd": effective_margin * int(args.leverage),
            "hold_seconds": int(args.hold_seconds),
            "hard_stop_pct": float(args.hard_stop_pct),
            "take_profit_pct": float(args.take_profit_pct),
            "trailing_activation_pct": float(args.trailing_activation_pct),
            "trailing_drawdown_pct": float(args.trailing_drawdown_pct),
            "exit_cooldown_seconds": int(args.exit_cooldown_seconds),
            "max_execution_price_deviation_pct": float(args.max_execution_price_deviation_pct),
            "fresh_seconds": int(args.fresh_seconds),
            "poll_seconds": int(args.poll_seconds),
            "status_event_seconds": int(args.status_event_seconds),
            "max_market_size_fraction": float(args.max_market_size_fraction),
            "validate_demo_instruments": bool(args.validate_demo_instruments),
            "blocked_instruments": dict(state.get("blocked_instruments") or {}),
            "telegram_notifications_enabled": telegram_notifier is not None,
        }
        if not args.dry_run:
            await _reconcile_and_record(
                client,
                state=state,
                instruments=instruments,
                specs=specs,
                leverage=int(args.leverage),
                state_path=state_path,
            )
        _save_state(state_path, state)
        await _record_demo_event(
            "funding_oi_demo_started",
            message="Funding/OI demo trader started",
            state=state,
            status="running",
        )

        last_status_event_at = datetime.min.replace(tzinfo=timezone.utc)
        while datetime.now(timezone.utc) < stop_at:
            loops += 1
            snapshots = await load_recent_snapshots(instruments=instruments, history_seconds=args.history_seconds)
            latest_by_inst = _latest_by_instrument(snapshots)
            state["last_loop_at"] = datetime.now(timezone.utc).isoformat()
            state["snapshot_count_seen"] = len(snapshots)
            closed_this_loop = False

            if not args.dry_run:
                await _reconcile_and_record(
                    client,
                    state=state,
                    instruments=instruments,
                    specs=specs,
                    leverage=int(args.leverage),
                    state_path=state_path,
                )

            if state.get("open_position"):
                position = state["open_position"]
                latest = latest_by_inst.get(position["inst_id"])
                if latest is not None:
                    decision_latest = latest
                    if not args.dry_run:
                        try:
                            execution_ticker = await fetch_execution_ticker(client, str(position["inst_id"]))
                            deviation = _price_deviation_pct(float(latest["mid_price"]), execution_ticker["mid_price"])
                            decision_latest = {
                                **latest,
                                "mid_price": execution_ticker["mid_price"],
                                "last_price": execution_ticker["last_price"],
                            }
                            position["last_execution_price"] = execution_ticker["mid_price"]
                            position["last_execution_price_deviation_pct"] = deviation
                            if (
                                float(args.max_execution_price_deviation_pct) > 0.0
                                and deviation > float(args.max_execution_price_deviation_pct)
                            ):
                                await _record_demo_event(
                                    "funding_oi_price_mismatch",
                                    level="warning",
                                    message=(
                                        f"Using OKX executable price for {position['inst_id']} exit checks "
                                        f"because snapshot deviates by {deviation:.2f}%"
                                    ),
                                    pair=str(position["inst_id"]),
                                    state=state,
                                    details={
                                        "snapshot_price": latest["mid_price"],
                                        "execution_price": execution_ticker["mid_price"],
                                        "deviation_pct": deviation,
                                    },
                                )
                        except Exception as exc:
                            await _record_demo_event(
                                "funding_oi_price_check_error",
                                level="error",
                                message=str(exc),
                                pair=str(position["inst_id"]),
                                state=state,
                                details={"snapshot_price": latest["mid_price"]},
                            )
                            continue
                    update_position_peak(position, decision_latest)
                    close_reason = _close_reason(
                        position=position,
                        latest=decision_latest,
                        hold_seconds=int(args.hold_seconds),
                        hard_stop_pct=float(args.hard_stop_pct),
                        take_profit_pct=float(args.take_profit_pct),
                        trailing_activation_pct=float(args.trailing_activation_pct),
                        trailing_drawdown_pct=float(args.trailing_drawdown_pct),
                    )
                    if close_reason:
                        if args.dry_run:
                            close_result = {"dry_run": True}
                            exit_price = float(latest["mid_price"])
                            closed_size = Decimal(str(position["size"]))
                            remaining_size = Decimal("0")
                        else:
                            try:
                                close_result = await close_position_with_confirmation(
                                    client,
                                    position=position,
                                    leverage=int(args.leverage),
                                    spec=specs[position["inst_id"]],
                                )
                                exit_price = float(close_result["avg_price"])
                                closed_size = Decimal(str(close_result["executed_size"]))
                                remaining_size = max(Decimal(str(position["size"])) - closed_size, Decimal("0"))
                            except PositionAlreadyFlatError as exc:
                                item = mark_position_exchange_flat(state, position=position, reason=str(exc))
                                closed_this_loop = True
                                await _record_demo_event(
                                    "funding_oi_position_reconciled",
                                    level="warning",
                                    message=item["message"],
                                    pair=str(position["inst_id"]),
                                    state=state,
                                    details={"reconciliation": item},
                                )
                                continue
                            except Exception as exc:
                                state.setdefault("close_errors", []).append(
                                    {
                                        "inst_id": position["inst_id"],
                                        "attempted_at": datetime.now(timezone.utc).isoformat(),
                                        "close_reason": close_reason,
                                        "size": position["size"],
                                        "error": str(exc),
                                    }
                                )
                                _save_state(state_path, state)
                                await _record_demo_event(
                                    "funding_oi_close_error",
                                    level="error",
                                    message=str(exc),
                                    pair=str(position["inst_id"]),
                                    state=state,
                                    details={"close_reason": close_reason, "size": position["size"]},
                                )
                                continue

                        trade = _closed_trade_payload(
                            position,
                            decision_latest,
                            exit_price,
                            close_reason,
                            close_result,
                            closed_size=closed_size,
                        )
                        state["closed_trades"].append(trade)
                        state.setdefault("last_exit_by_instrument", {})[str(position["inst_id"])] = datetime.now(timezone.utc).isoformat()
                        if remaining_size > 0:
                            position["size"] = _decimal_to_okx_size(remaining_size)
                            position["notional_usd"] = float(
                                remaining_size
                                * Decimal(str(position["ct_val"]))
                                * Decimal(str(latest["mid_price"]))
                            )
                            state["open_position"] = position
                            await _record_demo_event(
                                "funding_oi_position_partially_closed",
                                level="warning",
                                message=f"Partially closed {position['inst_id']} via {close_reason}",
                                pair=str(position["inst_id"]),
                                state=state,
                                details={"closed_trade": trade, "remaining_size": position["size"]},
                            )
                        else:
                            state["open_position"] = None
                            closed += 1
                            closed_this_loop = True
                            await _record_demo_event(
                                "funding_oi_position_closed",
                                message=f"Closed {position['inst_id']} via {close_reason}",
                                pair=str(position["inst_id"]),
                                state=state,
                                details={"closed_trade": trade},
                            )

            if state.get("open_position") is None and not closed_this_loop:
                processed_events = set(state.get("processed_events", []))
                blocked_instruments = set((state.get("blocked_instruments") or {}).keys())
                event = choose_fresh_event(
                    snapshots,
                    processed_events=processed_events,
                    blocked_instruments=blocked_instruments,
                    last_exit_by_instrument=state.get("last_exit_by_instrument") or {},
                    exit_cooldown_seconds=int(args.exit_cooldown_seconds),
                    fresh_seconds=int(args.fresh_seconds),
                    lookback_seconds=int(args.lookback_seconds),
                    min_abs_move_pct=float(args.min_abs_move_pct),
                    min_abs_funding_rate=float(args.min_abs_funding_rate),
                    min_oi_change_pct=float(args.min_oi_change_pct),
                    cooldown_seconds=int(args.cooldown_seconds),
                )
                if event is not None:
                    latest = latest_by_inst.get(event.inst_id)
                    if latest is not None:
                        price = float(latest["mid_price"])
                        execution_ticker: dict[str, Any] | None = None
                        if not args.dry_run:
                            try:
                                execution_ticker = await fetch_execution_ticker(client, event.inst_id)
                                ensure_execution_price_aligned(
                                    pair=event.inst_id,
                                    snapshot_price=price,
                                    execution_price=execution_ticker["mid_price"],
                                    max_deviation_pct=float(args.max_execution_price_deviation_pct),
                                )
                                price = execution_ticker["mid_price"]
                            except ExecutionPriceMismatchError as exc:
                                state.setdefault("blocked_instruments", {})[event.inst_id] = str(exc)
                                if isinstance(state.get("config"), dict):
                                    state["config"]["blocked_instruments"] = dict(state.get("blocked_instruments") or {})
                                event_key = _event_key(event.inst_id, event.occurred_at)
                                state["processed_events"].append(event_key)
                                _save_state(state_path, state)
                                await _record_demo_event(
                                    "funding_oi_price_mismatch",
                                    level="error",
                                    message=str(exc),
                                    pair=event.inst_id,
                                    state=state,
                                    details={
                                        "event_key": event_key,
                                        "snapshot_price": latest["mid_price"],
                                        "execution_ticker": execution_ticker,
                                    },
                                )
                                continue
                            except Exception as exc:
                                if _is_unknown_instrument_error(str(exc)):
                                    state.setdefault("blocked_instruments", {})[event.inst_id] = str(exc)
                                    instruments = tuple(inst_id for inst_id in instruments if inst_id != event.inst_id)
                                    specs.pop(event.inst_id, None)
                                event_key = _event_key(event.inst_id, event.occurred_at)
                                state["processed_events"].append(event_key)
                                if isinstance(state.get("config"), dict):
                                    state["config"]["instruments"] = list(instruments)
                                    state["config"]["blocked_instruments"] = dict(state.get("blocked_instruments") or {})
                                _save_state(state_path, state)
                                await _record_demo_event(
                                    "funding_oi_price_check_error",
                                    level="error",
                                    message=str(exc),
                                    pair=event.inst_id,
                                    state=state,
                                    details={
                                        "event_key": event_key,
                                        "snapshot_price": latest["mid_price"],
                                    },
                                )
                                continue
                        size = calculate_order_size_with_market_cap(
                            notional_usd=effective_margin * int(args.leverage),
                            price=price,
                            spec=specs[event.inst_id],
                            max_market_size_fraction=float(args.max_market_size_fraction),
                        )
                        event_key = _event_key(event.inst_id, event.occurred_at)
                        await _record_demo_event(
                            "funding_oi_signal",
                            message=f"Long signal detected on {event.inst_id}",
                            pair=event.inst_id,
                            state=state,
                            details={
                                "event_key": event_key,
                                "score": event.score,
                                "features": asdict(event.features),
                            },
                        )
                        if args.dry_run:
                            open_result = {"dry_run": True, "clOrdId": ""}
                            entry_price = price
                            filled_size = size
                        else:
                            try:
                                await client.set_leverage(event.inst_id, int(args.leverage))
                                open_result = await _place_market_with_size_retry(
                                    client,
                                    pair=event.inst_id,
                                    side="buy",
                                    size=size,
                                    spec=specs[event.inst_id],
                                    leverage=int(args.leverage),
                                    pos_side="long",
                                )
                                filled_size = Decimal(str(open_result["executed_size"]))
                                entry_price = float(open_result["avg_price"])
                            except Exception as exc:
                                if _is_unknown_instrument_error(str(exc)):
                                    state.setdefault("blocked_instruments", {})[event.inst_id] = str(exc)
                                    instruments = tuple(inst_id for inst_id in instruments if inst_id != event.inst_id)
                                    specs.pop(event.inst_id, None)
                                    if isinstance(state.get("config"), dict):
                                        state["config"]["instruments"] = list(instruments)
                                        state["config"]["blocked_instruments"] = dict(state.get("blocked_instruments") or {})
                                state.setdefault("order_errors", []).append(
                                    {
                                        "inst_id": event.inst_id,
                                        "event_key": event_key,
                                        "attempted_at": datetime.now(timezone.utc).isoformat(),
                                        "attempted_size": _decimal_to_okx_size(size),
                                        "error": str(exc),
                                    }
                                )
                                state["processed_events"].append(event_key)
                                _save_state(state_path, state)
                                await _record_demo_event(
                                    "funding_oi_order_error",
                                    level="error",
                                    message=str(exc),
                                    pair=event.inst_id,
                                    state=state,
                                    details={
                                        "event_key": event_key,
                                        "attempted_size": _decimal_to_okx_size(size),
                                    },
                                )
                                continue
                        state["processed_events"].append(event_key)
                        state["open_position"] = {
                            "inst_id": event.inst_id,
                            "side": "long",
                            "event_key": event_key,
                            "event_at": event.occurred_at.isoformat(),
                            "opened_at": datetime.now(timezone.utc).isoformat(),
                            "entry_price": entry_price,
                            "size": _decimal_to_okx_size(filled_size),
                            "ct_val": str(specs[event.inst_id].ct_val),
                            "notional_usd": float(filled_size * specs[event.inst_id].ct_val * Decimal(str(entry_price))),
                            "margin_usd": effective_margin,
                            "leverage": int(args.leverage),
                            "peak_price": entry_price,
                            "peak_move_pct": 0.0,
                            "features": asdict(event.features),
                            "open_result": open_result,
                        }
                        opened += 1
                        await _record_demo_event(
                            "funding_oi_position_opened",
                            message=f"Opened {event.inst_id} long",
                            pair=event.inst_id,
                            state=state,
                            details={
                                "event_key": event_key,
                                "entry_price": entry_price,
                                "size": _decimal_to_okx_size(filled_size),
                            },
                        )

            _save_state(state_path, state)
            now = datetime.now(timezone.utc)
            if now - last_status_event_at >= timedelta(seconds=max(5, int(args.status_event_seconds))):
                await _record_demo_event(
                    "funding_oi_demo_status",
                    message="Funding/OI demo trader heartbeat",
                    state=state,
                    status="running",
                )
                last_status_event_at = now
            await asyncio.sleep(max(1, int(args.poll_seconds)))
    finally:
        _save_state(state_path, state)
        await _record_demo_event(
            "funding_oi_demo_stopped",
            message="Funding/OI demo trader stopped",
            state=state,
            status="stopped",
        )
        if telegram_notifier is not None:
            await telegram_notifier.close()
        _set_demo_telegram_notifier(None)
        await client.close()

    return {
        "status": "finished",
        "loops": loops,
        "opened": opened,
        "closed": closed,
        "state_file": str(state_path),
        "open_position": state.get("open_position"),
        "closed_trade_count": len(state.get("closed_trades", [])),
    }


async def _place_market_with_size_retry(
    client: OKXClient,
    *,
    pair: str,
    side: str,
    size: Decimal,
    spec: InstrumentSpec,
    leverage: int,
    pos_side: str,
) -> dict[str, Any]:
    current = size
    errors: list[str] = []
    for _ in range(8):
        try:
            result = await _place_with_pos_side_fallback(
                client,
                pair=pair,
                side=side,
                size=_decimal_to_okx_size(current),
                leverage=leverage,
                pos_side=pos_side,
                reduce_only=False,
            )
            confirmed = await _confirm_order_execution(
                client,
                pair=pair,
                cl_ord_id=str(result["clOrdId"]),
                requested_size=current,
            )
            result.update(confirmed)
            if errors:
                result["size_retry_errors"] = errors
            return result
        except OrderNotFilledError as exc:
            exchange_position = await _find_exchange_position(client, pair=pair)
            if exchange_position is None:
                raise
            result.update(_confirmation_from_exchange_position(exchange_position, source_error=str(exc)))
            if errors:
                result["size_retry_errors"] = errors
            return result
        except RuntimeError as exc:
            message = str(exc)
            if not _is_retryable_size_error(message):
                raise
            errors.append(message)
            next_size = ((current / Decimal("2")) / spec.lot_size).to_integral_value(rounding=ROUND_DOWN) * spec.lot_size
            if next_size < spec.min_size:
                raise RuntimeError(
                    f"market order size rejected and retry size below min size for {pair}: {errors}"
                ) from exc
            current = next_size
    raise RuntimeError(f"market order size rejected after retries for {pair}: {errors}")


def _is_retryable_size_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "51202" in message
        or "maximum amount" in normalized
        or "51008" in message
        or "insufficient" in normalized
    )


def _is_unknown_instrument_error(message: str) -> bool:
    normalized = message.lower()
    return "51001" in message or ("instrument id" in normalized and "doesn't exist" in normalized)


def _is_position_flat_error(message: str) -> bool:
    normalized = message.lower()
    return "51169" in message or "don't have any positions" in normalized


async def close_position_with_confirmation(
    client: OKXClient,
    *,
    position: Mapping[str, Any],
    leverage: int,
    spec: InstrumentSpec,
) -> dict[str, Any]:
    pair = str(position["inst_id"])
    size = Decimal(str(position["size"]))
    await cancel_pending_close_orders(client, pair=pair)
    try:
        result = await _place_with_pos_side_fallback(
            client,
            pair=pair,
            side="sell",
            size=_decimal_to_okx_size(size),
            leverage=leverage,
            pos_side=LONG_POS_SIDE,
            reduce_only=True,
        )
    except RuntimeError as exc:
        if _is_position_flat_error(str(exc)):
            raise PositionAlreadyFlatError(str(exc)) from exc
        raise

    try:
        confirmed = await _confirm_order_execution(
            client,
            pair=pair,
            cl_ord_id=str(result["clOrdId"]),
            requested_size=size,
        )
    except OrderNotFilledError as exc:
        exchange_position = await _find_exchange_position(client, pair=pair)
        if exchange_position is None:
            raise PositionAlreadyFlatError(str(exc)) from exc
        raise

    result.update(confirmed)
    closed_size = Decimal(str(result["executed_size"]))
    if closed_size <= 0:
        raise OrderNotFilledError(f"close order did not fill for {pair}")
    if closed_size < spec.min_size:
        raise OrderNotFilledError(f"close order fill {closed_size} is below min size for {pair}")
    return result


async def cancel_pending_close_orders(client: OKXClient, *, pair: str) -> list[dict[str, Any]]:
    canceled: list[dict[str, Any]] = []
    try:
        pending = await client.get_pending_orders()
    except Exception:
        return canceled
    for order in pending:
        if order.get("instId") != pair:
            continue
        if str(order.get("side")) != "sell":
            continue
        if str(order.get("posSide") or LONG_POS_SIDE) not in (LONG_POS_SIDE, "net"):
            continue
        ord_id = order.get("ordId")
        if not ord_id:
            continue
        try:
            result = await client._request(
                "POST",
                "/api/v5/trade/cancel-order",
                data={"instId": pair, "ordId": ord_id},
            )
            canceled.append({"ordId": ord_id, "result": result})
        except Exception as exc:
            canceled.append({"ordId": ord_id, "error": str(exc)})
    return canceled


async def cancel_order_by_detail(client: OKXClient, *, pair: str, detail: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not detail:
        return None
    payload: dict[str, Any] = {"instId": pair}
    ord_id = detail.get("ordId")
    cl_ord_id = detail.get("clOrdId")
    if ord_id:
        payload["ordId"] = ord_id
    elif cl_ord_id:
        payload["clOrdId"] = cl_ord_id
    else:
        return None
    return await client._request("POST", "/api/v5/trade/cancel-order", data=payload)


async def _find_exchange_position(client: OKXClient, *, pair: str) -> Mapping[str, Any] | None:
    positions = await client.get_positions()
    for row in positions:
        if row.get("instId") != pair:
            continue
        if str(row.get("posSide") or LONG_POS_SIDE) not in (LONG_POS_SIDE, "net"):
            continue
        if _positive_position_size(row) > 0:
            return row
    return None


def _confirmation_from_exchange_position(position: Mapping[str, Any], *, source_error: str) -> dict[str, Any]:
    size = _positive_position_size(position)
    avg_price = _optional_decimal(position.get("avgPx")) or _optional_decimal(position.get("markPx"))
    if size <= 0 or avg_price is None or avg_price <= 0:
        raise OrderNotFilledError(f"exchange position is not usable after confirmation failure: {position}")
    return {
        "executed_size": _decimal_to_okx_size(size),
        "avg_price": float(avg_price),
        "order_state": "exchange_position_adopted",
        "order_detail": dict(position),
        "confirmation_warning": source_error,
    }


async def _confirm_order_execution(
    client: OKXClient,
    *,
    pair: str,
    cl_ord_id: str,
    requested_size: Decimal,
) -> dict[str, Any]:
    last_detail: dict[str, Any] | None = None
    for _ in range(12):
        detail = await client.get_order_by_cl_ord_id(cl_ord_id, pair=pair)
        last_detail = detail
        executed_size = _order_executed_size(detail)
        avg_price = _order_avg_price(detail)
        state = str(detail.get("state") or "")
        if executed_size > 0 and avg_price > 0:
            if state == "filled" or executed_size >= requested_size:
                return {
                    "executed_size": _decimal_to_okx_size(executed_size),
                    "avg_price": float(avg_price),
                    "order_state": state,
                    "order_detail": detail,
                }
            if state in {"canceled", "cancelled", "rejected"}:
                return {
                    "executed_size": _decimal_to_okx_size(executed_size),
                    "avg_price": float(avg_price),
                    "order_state": state,
                    "order_detail": detail,
                }
        if state in {"canceled", "cancelled", "rejected"}:
            raise OrderNotFilledError(
                f"order {cl_ord_id} ended state={state} with accFillSz={executed_size}"
            )
        await asyncio.sleep(0.5)
    cancel_result: dict[str, Any] | None = None
    try:
        cancel_result = await cancel_order_by_detail(client, pair=pair, detail=last_detail)
    except Exception as exc:
        raise OrderNotFilledError(
            f"order {cl_ord_id} did not confirm filled and cancel failed: {exc}; last_detail={last_detail}"
        ) from exc

    detail = await client.get_order_by_cl_ord_id(cl_ord_id, pair=pair)
    executed_size = _order_executed_size(detail)
    avg_price = _order_avg_price(detail)
    if executed_size > 0 and avg_price > 0:
        return {
            "executed_size": _decimal_to_okx_size(executed_size),
            "avg_price": float(avg_price),
            "order_state": str(detail.get("state") or "canceled_after_timeout"),
            "order_detail": detail,
            "cancel_result": cancel_result,
        }
    raise OrderNotFilledError(f"order {cl_ord_id} did not confirm filled and was canceled: {detail}")


def _order_executed_size(detail: Mapping[str, Any]) -> Decimal:
    return _optional_decimal(detail.get("accFillSz")) or _optional_decimal(detail.get("fillSz")) or Decimal("0")


def _order_avg_price(detail: Mapping[str, Any]) -> Decimal:
    return _optional_decimal(detail.get("avgPx")) or _optional_decimal(detail.get("fillPx")) or Decimal("0")


async def _place_with_pos_side_fallback(
    client: OKXClient,
    *,
    pair: str,
    side: str,
    size: str,
    leverage: int,
    pos_side: str,
    reduce_only: bool,
) -> dict[str, Any]:
    cl_ord_id = uuid4().hex
    try:
        result = await client.place_order(
            pair=pair,
            side=side,
            size=size,
            leverage=leverage,
            order_type="market",
            cl_ord_id=cl_ord_id,
            pos_side=pos_side,
            reduce_only=reduce_only,
        )
        result["clOrdId"] = cl_ord_id
        return result
    except RuntimeError as exc:
        if "posSide" not in str(exc) and "position mode" not in str(exc).lower():
            raise

    fallback_cl_ord_id = uuid4().hex
    result = await client.place_order(
        pair=pair,
        side=side,
        size=size,
        leverage=leverage,
        order_type="market",
        cl_ord_id=fallback_cl_ord_id,
        pos_side=None,
        reduce_only=reduce_only,
    )
    result["clOrdId"] = fallback_cl_ord_id
    result["pos_side_fallback"] = True
    return result


async def _fetch_fill_price(client: OKXClient, cl_ord_id: str, pair: str, *, fallback: float) -> float:
    if not cl_ord_id:
        return fallback
    for _ in range(8):
        try:
            detail = await client.get_order_by_cl_ord_id(cl_ord_id, pair=pair)
            avg_px = float(detail.get("avgPx") or detail.get("fillPx") or 0.0)
            if avg_px > 0:
                return avg_px
        except Exception:
            pass
        await asyncio.sleep(0.4)
    return fallback


def _snapshot_payload(row: Any) -> dict[str, Any]:
    return {
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


def _latest_by_instrument(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in snapshots:
        inst_id = str(row["inst_id"])
        if inst_id not in latest or row["observed_at"] > latest[inst_id]["observed_at"]:
            latest[inst_id] = row
    return latest


def update_position_peak(position: dict[str, Any], latest: Mapping[str, Any]) -> None:
    entry_price = float(position["entry_price"])
    current_price = float(latest["mid_price"])
    if entry_price <= 0.0 or current_price <= 0.0:
        return
    peak_price = max(float(position.get("peak_price") or entry_price), current_price)
    peak_move_pct = max(
        float(position.get("peak_move_pct") or 0.0),
        ((peak_price / entry_price) - 1.0) * 100.0,
    )
    position["peak_price"] = peak_price
    position["peak_move_pct"] = peak_move_pct


def _close_reason(
    *,
    position: Mapping[str, Any],
    latest: Mapping[str, Any],
    hold_seconds: int,
    hard_stop_pct: float,
    take_profit_pct: float,
    trailing_activation_pct: float,
    trailing_drawdown_pct: float,
) -> str | None:
    opened_at = datetime.fromisoformat(str(position["opened_at"]))
    entry_price = float(position["entry_price"])
    current_price = float(latest["mid_price"])
    if entry_price > 0.0:
        move_pct = ((current_price / entry_price) - 1.0) * 100.0
        if move_pct <= -hard_stop_pct:
            return "hard_stop"
        if take_profit_pct > 0.0 and move_pct >= take_profit_pct:
            return "take_profit"
        peak_move_pct = float(position.get("peak_move_pct") or move_pct)
        if (
            trailing_activation_pct > 0.0
            and trailing_drawdown_pct > 0.0
            and peak_move_pct >= trailing_activation_pct
            and (peak_move_pct - move_pct) >= trailing_drawdown_pct
        ):
            return "trailing_stop"
    if datetime.now(timezone.utc) - opened_at >= timedelta(seconds=hold_seconds):
        return "time_exit"
    return None


def _closed_trade_payload(
    position: Mapping[str, Any],
    latest: Mapping[str, Any],
    exit_price: float,
    close_reason: str,
    close_result: Mapping[str, Any],
    *,
    closed_size: Decimal | None = None,
) -> dict[str, Any]:
    entry_price = float(position["entry_price"])
    size = closed_size or Decimal(str(position["size"]))
    ct_val = Decimal(str(position["ct_val"]))
    pnl = (Decimal(str(exit_price)) - Decimal(str(entry_price))) * size * ct_val
    notional = Decimal(str(entry_price)) * size * ct_val
    pnl_pct = (pnl / notional * Decimal("100")) if notional > 0 else Decimal("0")
    return {
        "inst_id": position["inst_id"],
        "side": position["side"],
        "opened_at": position["opened_at"],
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": _decimal_to_okx_size(size),
        "ct_val": position["ct_val"],
        "pnl_usd_estimate": float(pnl),
        "pnl_pct_estimate": float(pnl_pct),
        "close_reason": close_reason,
        "latest_snapshot_at": latest["observed_at"].isoformat(),
        "close_result": dict(close_result),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def _set_demo_telegram_notifier(notifier: Any | None) -> None:
    global _DEMO_TELEGRAM_NOTIFIER
    _DEMO_TELEGRAM_NOTIFIER = notifier


def _build_demo_telegram_notifier(settings: Any) -> Any | None:
    if not getattr(settings, "telegram_enabled", False):
        return None
    from app.core.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        chat_id=settings.TELEGRAM_CHAT_ID,
        enabled=True,
    )
    return notifier if notifier.enabled else None


async def _record_demo_event(
    event: str,
    *,
    level: str = "info",
    message: str | None = None,
    pair: str | None = None,
    state: Mapping[str, Any] | None = None,
    status: str = "running",
    details: Mapping[str, Any] | None = None,
) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.runtime_event import RuntimeEvent

    payload: dict[str, Any] = {}
    if state is not None:
        payload.update(_demo_status_details(state, status=status))
    if details:
        payload.update(details)

    async with AsyncSessionLocal() as session:
        session.add(
            RuntimeEvent(
                timestamp=datetime.now(timezone.utc),
                level=level,
                event=event,
                pair=pair,
                strategy=STRATEGY_NAME,
                timeframe="snapshot",
                message=message,
                details_json=_json_safe(payload),
            )
        )
        await session.commit()

    await _send_demo_telegram_event(
        event,
        level=level,
        message=message,
        pair=pair,
        state=state,
        status=status,
        details=payload,
    )


async def _send_demo_telegram_event(
    event: str,
    *,
    level: str,
    message: str | None,
    pair: str | None,
    state: Mapping[str, Any] | None,
    status: str,
    details: Mapping[str, Any],
) -> None:
    notifier = _DEMO_TELEGRAM_NOTIFIER
    if notifier is None:
        return
    text = _demo_telegram_message(
        event,
        level=level,
        message=message,
        pair=pair,
        state=state,
        status=status,
        details=details,
    )
    if text is None:
        return
    try:
        await notifier.send_text(text)
    except Exception:
        return


def _demo_telegram_message(
    event: str,
    *,
    level: str,
    message: str | None,
    pair: str | None,
    state: Mapping[str, Any] | None,
    status: str,
    details: Mapping[str, Any],
) -> str | None:
    label = _TELEGRAM_EVENT_LABELS.get(event)
    if label is None:
        return None

    lines = [
        "[OKX 데모 트레이더]",
        f"이벤트: {label}",
        f"전략: {STRATEGY_NAME}",
        f"상태: {status}",
    ]
    if pair:
        lines.append(f"종목: {pair}")
    if message:
        lines.append(f"내용: {message}")

    config = dict((state or {}).get("config") or {})
    if event in {"funding_oi_demo_started", "funding_oi_demo_stopped"}:
        watched = config.get("instruments") or []
        lines.extend(
            [
                f"감시 종목 수: {len(watched)}",
                f"레버리지: {config.get('leverage', '-')}",
                f"증거금: {_format_usd(config.get('effective_margin_usd'))}",
                f"명목금액: {_format_usd(config.get('notional_usd'))}",
            ]
        )

    if event == "funding_oi_signal":
        score = details.get("score")
        features = dict(details.get("features") or {})
        lines.append(f"점수: {_format_number(score, digits=0)}")
        _append_feature_lines(lines, features)

    if event == "funding_oi_position_opened":
        open_position = dict((state or {}).get("open_position") or {})
        lines.extend(
            [
                f"진입가: {_format_number(details.get('entry_price') or open_position.get('entry_price'), digits=6)}",
                f"수량: {details.get('size') or open_position.get('size') or '-'}",
                f"포지션 명목금액: {_format_usd(open_position.get('notional_usd'))}",
            ]
        )
        _append_feature_lines(lines, dict(open_position.get("features") or {}))

    closed_trade = details.get("closed_trade")
    if isinstance(closed_trade, Mapping):
        lines.extend(
            [
                f"진입가: {_format_number(closed_trade.get('entry_price'), digits=6)}",
                f"청산가: {_format_number(closed_trade.get('exit_price'), digits=6)}",
                f"손익 추정: {_format_signed_usd(closed_trade.get('pnl_usd_estimate'))}",
                f"수익률 추정: {_format_pct(closed_trade.get('pnl_pct_estimate'), digits=3)}",
                f"청산 이유: {closed_trade.get('close_reason') or '-'}",
            ]
        )

    reconciliation = details.get("reconciliation")
    if isinstance(reconciliation, Mapping):
        lines.append(f"동기화 내용: {reconciliation.get('type') or '-'}")
        reason = reconciliation.get("reason")
        if reason:
            lines.append(f"이유: {reason}")

    if level in {"warning", "error"}:
        close_reason = details.get("close_reason")
        attempted_size = details.get("attempted_size") or details.get("size")
        if close_reason:
            lines.append(f"청산 조건: {close_reason}")
        if attempted_size:
            lines.append(f"시도 수량: {attempted_size}")

    return "\n".join(line for line in lines if line)


def _append_feature_lines(lines: list[str], features: Mapping[str, Any]) -> None:
    if not features:
        return
    lines.extend(
        [
            f"가격 움직임: {_format_pct(features.get('lookback_return_pct'), digits=2)}",
            f"펀딩비: {_format_rate_as_pct(features.get('funding_rate'), digits=4)}",
            f"OI 변화: {_format_pct(features.get('oi_change_pct'), digits=2)}",
            f"스프레드: {_format_pct(features.get('spread_pct'), digits=3)}",
            f"셋업: {features.get('setup') or '-'}",
        ]
    )


def _format_usd(value: Any) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"${parsed:,.2f}"


def _format_signed_usd(value: Any) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed:+,.2f} USDT"


def _format_number(value: Any, *, digits: int) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed:,.{digits}f}"


def _format_pct(value: Any, *, digits: int) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed:+.{digits}f}%"


def _format_rate_as_pct(value: Any, *, digits: int) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed * 100:+.{digits}f}%"


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _demo_status_details(state: Mapping[str, Any], *, status: str) -> dict[str, Any]:
    config = dict(state.get("config") or {})
    instruments = list(config.get("instruments") or [])
    status_event_seconds = int(config.get("status_event_seconds") or 30)
    open_position = state.get("open_position")
    return {
        "status": status,
        "strategy_name": state.get("strategy_name") or STRATEGY_NAME,
        "mode": state.get("mode"),
        "dry_run": bool(state.get("dry_run")),
        "started_at": state.get("started_at"),
        "last_loop_at": state.get("last_loop_at"),
        "snapshot_count_seen": state.get("snapshot_count_seen"),
        "open_position": _public_position(open_position) if isinstance(open_position, Mapping) else None,
        "closed_trade_count": len(state.get("closed_trades") or []),
        "processed_event_count": len(state.get("processed_events") or []),
        "order_error_count": len(state.get("order_errors") or []),
        "close_error_count": len(state.get("close_errors") or []),
        "reconciliation_count": len(state.get("reconciliations") or []),
        "reconciliation_error_count": len(state.get("reconciliation_errors") or []),
        "config": config,
        "watched_instrument_count": len(instruments),
        "watched_instruments": instruments,
        "stale_after_seconds": max(90, status_event_seconds * 4),
    }


def _public_position(position: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "inst_id",
        "side",
        "event_key",
        "event_at",
        "opened_at",
        "entry_price",
        "size",
        "ct_val",
        "notional_usd",
        "margin_usd",
        "leverage",
        "peak_price",
        "peak_move_pct",
        "features",
    )
    return {key: position[key] for key in keys if key in position}


def _json_safe(payload: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))


def _event_key(inst_id: str, occurred_at: datetime) -> str:
    return f"{inst_id}:{occurred_at.isoformat()}"


def _positive_decimal(value: Any, *, default: str) -> Decimal:
    parsed = Decimal(str(value if value not in (None, "") else default))
    return parsed if parsed > 0 else Decimal(default)


def _optional_positive_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    return parsed if parsed > 0 else None


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _positive_position_size(row: Mapping[str, Any]) -> Decimal:
    value = _optional_decimal(row.get("pos"))
    if value is None:
        return Decimal("0")
    return abs(value)


def _decimal_to_okx_size(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
