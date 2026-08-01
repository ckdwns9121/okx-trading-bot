"""Reconciliation: compare the bot's internal book against the exchange.

Institutions reconcile continuously because the internal book silently
drifting away from the exchange (partial fills, rejected orders, manual
trades, API bugs) is how small bugs become large losses. Retail bots get the
same protection from a periodic REST comparison.

The core comparison is pure and fully unit-testable; ``run_reconciliation``
is a thin async wrapper that feeds it live OKX data and the local Position
table, and optionally trips the kill switch on critical mismatches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from app.core.risk_gate import KillSwitch

CRITICAL_KINDS = frozenset(
    {"unexpected_on_exchange", "missing_on_exchange", "size_mismatch", "direction_mismatch"}
)


@dataclass(frozen=True)
class Discrepancy:
    kind: str
    inst_id: str
    detail: str
    local: dict[str, Any] | None = None
    exchange: dict[str, Any] | None = None

    @property
    def critical(self) -> bool:
        return self.kind in CRITICAL_KINDS


@dataclass(frozen=True)
class ReconciliationReport:
    checked_at: datetime
    local_position_count: int
    exchange_position_count: int
    discrepancies: tuple[Discrepancy, ...]

    @property
    def ok(self) -> bool:
        return not self.discrepancies

    @property
    def critical(self) -> bool:
        return any(item.critical for item in self.discrepancies)

    def to_payload(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "ok": self.ok,
            "critical": self.critical,
            "local_position_count": self.local_position_count,
            "exchange_position_count": self.exchange_position_count,
            "discrepancies": [
                {
                    "kind": item.kind,
                    "inst_id": item.inst_id,
                    "critical": item.critical,
                    "detail": item.detail,
                    "local": item.local,
                    "exchange": item.exchange,
                }
                for item in self.discrepancies
            ],
        }


def _normalize_exchange_positions(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Convert raw OKX position rows into {inst_id: {direction, quantity}}."""

    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst_id = str(row.get("instId") or "")
        if not inst_id:
            continue
        try:
            pos = float(row.get("pos") or 0.0)
        except (TypeError, ValueError):
            continue
        if pos == 0.0:
            continue

        pos_side = str(row.get("posSide") or "net")
        if pos_side == "long":
            direction = "long"
        elif pos_side == "short":
            direction = "short"
        else:  # net mode: sign of pos carries direction
            direction = "long" if pos > 0 else "short"

        normalized[inst_id] = {
            "direction": direction,
            "quantity": abs(pos),
            "avg_price": _optional_float(row.get("avgPx")),
        }
    return normalized


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def reconcile_positions(
    local_positions: Iterable[Mapping[str, Any]],
    exchange_rows: Iterable[Mapping[str, Any]],
    *,
    size_tolerance_pct: float = 0.5,
    now: datetime | None = None,
) -> ReconciliationReport:
    """Compare local open positions against exchange position rows.

    ``local_positions`` items need: inst_id (or pair), direction, quantity.
    ``exchange_rows`` are raw OKX /account/positions rows.
    """

    if size_tolerance_pct < 0.0:
        raise ValueError("size_tolerance_pct cannot be negative")

    checked_at = now or datetime.now(timezone.utc)
    exchange = _normalize_exchange_positions(exchange_rows)

    local: dict[str, dict[str, Any]] = {}
    for row in local_positions:
        inst_id = str(row.get("inst_id") or row.get("pair") or "")
        quantity = float(row.get("quantity") or 0.0)
        if not inst_id or quantity <= 0.0:
            continue
        local[inst_id] = {
            "direction": str(row.get("direction") or "long"),
            "quantity": quantity,
        }

    discrepancies: list[Discrepancy] = []

    for inst_id, local_row in local.items():
        exchange_row = exchange.get(inst_id)
        if exchange_row is None:
            discrepancies.append(
                Discrepancy(
                    kind="missing_on_exchange",
                    inst_id=inst_id,
                    detail="local book has an open position but the exchange is flat",
                    local=local_row,
                )
            )
            continue

        if local_row["direction"] != exchange_row["direction"]:
            discrepancies.append(
                Discrepancy(
                    kind="direction_mismatch",
                    inst_id=inst_id,
                    detail=(
                        f"local direction {local_row['direction']} !="
                        f" exchange direction {exchange_row['direction']}"
                    ),
                    local=local_row,
                    exchange=exchange_row,
                )
            )
            continue

        local_qty = float(local_row["quantity"])
        exchange_qty = float(exchange_row["quantity"])
        deviation_pct = abs(exchange_qty - local_qty) / local_qty * 100.0
        if deviation_pct > size_tolerance_pct:
            discrepancies.append(
                Discrepancy(
                    kind="size_mismatch",
                    inst_id=inst_id,
                    detail=(
                        f"local size {local_qty} vs exchange size {exchange_qty}"
                        f" ({deviation_pct:.2f}% deviation, tolerance {size_tolerance_pct}%)"
                    ),
                    local=local_row,
                    exchange=exchange_row,
                )
            )

    for inst_id, exchange_row in exchange.items():
        if inst_id not in local:
            discrepancies.append(
                Discrepancy(
                    kind="unexpected_on_exchange",
                    inst_id=inst_id,
                    detail="exchange has an open position that is not in the local book",
                    exchange=exchange_row,
                )
            )

    return ReconciliationReport(
        checked_at=checked_at,
        local_position_count=len(local),
        exchange_position_count=len(exchange),
        discrepancies=tuple(discrepancies),
    )


async def load_local_positions(session: Any) -> list[dict[str, Any]]:
    """Load open positions from the local Position table."""

    from sqlalchemy import select

    from app.models.position import Position

    result = await session.execute(select(Position))
    return [
        {
            "inst_id": row.pair,
            "direction": row.direction,
            "quantity": float(row.quantity),
        }
        for row in result.scalars().all()
    ]


async def run_reconciliation(
    *,
    okx_client: Any,
    session: Any,
    kill_switch: KillSwitch | None = None,
    size_tolerance_pct: float = 0.5,
    trip_on_critical: bool = False,
) -> ReconciliationReport:
    """Fetch both books and compare. Optionally trip the kill switch."""

    local_positions = await load_local_positions(session)
    exchange_rows = await okx_client.get_positions()
    report = reconcile_positions(
        local_positions,
        exchange_rows,
        size_tolerance_pct=size_tolerance_pct,
    )

    if report.critical and trip_on_critical and kill_switch is not None:
        kinds = sorted({item.kind for item in report.discrepancies if item.critical})
        kill_switch.trip(
            reason=f"reconciliation found critical discrepancies: {', '.join(kinds)}",
            source="reconciliation",
        )
    return report
