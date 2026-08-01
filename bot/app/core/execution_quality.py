"""Execution quality (TCA) recording.

For every order we store the decision price (what the signal saw) and the
fill price (what we actually got). The accumulated implementation shortfall
answers the one question backtests cannot: is the strategy dying, or is the
execution eating the edge? Records are appended to a JSONL file so any
runner (script, API, notebook) can write and read without a DB migration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


@dataclass(frozen=True)
class ExecutionRecord:
    inst_id: str
    side: str  # "buy" | "sell"
    quantity: float
    decision_price: float
    fill_price: float
    fee_usd: float = 0.0
    occurred_at: str = ""
    strategy: str | None = None
    order_ref: str | None = None

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if self.quantity <= 0.0:
            raise ValueError("quantity must be positive")
        if self.decision_price <= 0.0 or self.fill_price <= 0.0:
            raise ValueError("prices must be positive")
        if not self.occurred_at:
            object.__setattr__(self, "occurred_at", datetime.now(timezone.utc).isoformat())

    @property
    def slippage_pct(self) -> float:
        """Adverse slippage as a positive percentage.

        Buying above or selling below the decision price is adverse (> 0);
        price improvement is negative.
        """
        if self.side == "buy":
            return ((self.fill_price / self.decision_price) - 1.0) * 100.0
        return ((self.decision_price / self.fill_price) - 1.0) * 100.0

    @property
    def shortfall_usd(self) -> float:
        """Implementation shortfall in USD for this fill (fees included)."""
        per_unit = (
            self.fill_price - self.decision_price
            if self.side == "buy"
            else self.decision_price - self.fill_price
        )
        return per_unit * self.quantity + self.fee_usd


def summarize_execution_records(records: Iterable[ExecutionRecord]) -> dict[str, Any]:
    rows = list(records)
    if not rows:
        return {
            "count": 0,
            "avg_slippage_pct": 0.0,
            "median_slippage_pct": 0.0,
            "worst_slippage_pct": 0.0,
            "total_shortfall_usd": 0.0,
            "total_fees_usd": 0.0,
            "by_instrument": {},
        }

    slippages = [row.slippage_pct for row in rows]
    by_instrument: dict[str, list[ExecutionRecord]] = {}
    for row in rows:
        by_instrument.setdefault(row.inst_id, []).append(row)

    return {
        "count": len(rows),
        "avg_slippage_pct": mean(slippages),
        "median_slippage_pct": median(slippages),
        "worst_slippage_pct": max(slippages),
        "total_shortfall_usd": sum(row.shortfall_usd for row in rows),
        "total_fees_usd": sum(row.fee_usd for row in rows),
        "by_instrument": {
            inst_id: {
                "count": len(group),
                "avg_slippage_pct": mean(row.slippage_pct for row in group),
                "total_shortfall_usd": sum(row.shortfall_usd for row in group),
            }
            for inst_id, group in sorted(by_instrument.items())
        },
    }


class ExecutionQualityLog:
    """Append-only JSONL store for execution records."""

    def __init__(self, log_path: str | Path) -> None:
        self._log_path = Path(log_path)

    @property
    def log_path(self) -> Path:
        return self._log_path

    def record(self, record: ExecutionRecord) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def load(self, *, limit: int | None = None) -> list[ExecutionRecord]:
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

        records: list[ExecutionRecord] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                records.append(ExecutionRecord(**payload))
            except (json.JSONDecodeError, TypeError, ValueError):
                # A corrupt line must not take down reporting for the rest.
                continue
        if limit is not None:
            records = records[-limit:]
        return records

    def summary(self, *, limit: int | None = None) -> dict[str, Any]:
        return summarize_execution_records(self.load(limit=limit))
