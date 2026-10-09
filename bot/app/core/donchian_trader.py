"""Live/demo Donchian sleeve trader — pure decision and bookkeeping logic.

The runner (scripts/run_donchian_trader.py) does all I/O. Everything here is
deterministic so it can be unit tested:

- ``decide``: what one sleeve should do on the latest *confirmed* daily bar
- ``client_order_id``: deterministic id per (instrument, bar, side) — a restart
  can never send the same day's order twice
- ``is_fresh``: refuse to decide on stale data
- ``reconcile``: bot book vs exchange balances, ignoring holdings that were
  already in the account before the bot started (demo accounts come pre-funded)
- ``apply_fill``: update a sleeve from an exchange fill, fees in either currency
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.core.donchian_majors import Bars, DonchianParams, donchian_signal, position_fraction
from app.core.indicators import atr_wilder

DAY_MS = 86_400_000


@dataclass
class Sleeve:
    inst: str
    cash_usd: float  # USDT earmarked for this sleeve (not yet invested)
    qty: float = 0.0  # base currency the bot owns for this sleeve
    entry_px: float | None = None
    entry_atr: float | None = None
    entry_ts: int | None = None
    realized_pnl_usd: float = 0.0

    @property
    def base_ccy(self) -> str:
        return self.inst.split("-")[0]

    def in_position(self, price: float, min_notional: float) -> bool:
        return self.qty * price >= min_notional

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Sleeve":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class Decision:
    inst: str
    bar_ts: int
    action: str  # "buy" | "sell" | "none"
    reason: str
    close: float
    atr: float | None
    quote_to_spend: float = 0.0  # buy
    base_to_sell: float = 0.0  # sell
    fraction: float = 0.0


def candles_to_bars(inst: str, candles: Sequence[Mapping[str, Any]]) -> Bars:
    """Ascending, confirmed-only candles → Bars."""
    rows = [c for c in candles if str(c.get("confirm", "1")) == "1"]
    rows.sort(key=lambda c: int(c["timestamp"]))
    return Bars(
        inst,
        [int(c["timestamp"]) for c in rows],
        [float(c["open"]) for c in rows],
        [float(c["high"]) for c in rows],
        [float(c["low"]) for c in rows],
        [float(c["close"]) for c in rows],
    )


def expected_latest_bar_ts(now: datetime) -> int:
    """The daily (UTC) bar that should be confirmed by ``now``: yesterday 00:00 UTC."""
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return int(midnight.timestamp() * 1000) - DAY_MS


def is_fresh(latest_bar_ts: int, now: datetime) -> bool:
    return latest_bar_ts >= expected_latest_bar_ts(now)


def decide(bars: Bars, sleeve: Sleeve, params: DonchianParams, *, min_notional: float) -> Decision:
    """Signal on the last bar of ``bars`` (must already be confirmed)."""
    i = len(bars.ts) - 1
    close = bars.close[i]
    atr = atr_wilder(bars.high, bars.low, bars.close, params.atr_days)
    in_pos = sleeve.in_position(close, min_notional)
    sig = donchian_signal(bars, i, in_pos, sleeve.entry_px, sleeve.entry_atr, atr, params)
    atr_i = atr[i]
    if sig == "enter":
        frac = position_fraction(close, atr_i, params)
        spend = sleeve.cash_usd * frac
        if spend < min_notional:
            return Decision(sleeve.inst, bars.ts[i], "none", "entry_below_min_notional", close, atr_i, fraction=frac)
        return Decision(sleeve.inst, bars.ts[i], "buy", "breakout", close, atr_i, quote_to_spend=spend, fraction=frac)
    if sig.startswith("exit"):
        return Decision(sleeve.inst, bars.ts[i], "sell", sig.split(":", 1)[1], close, atr_i, base_to_sell=sleeve.qty)
    return Decision(sleeve.inst, bars.ts[i], "none", "in_position" if in_pos else "no_signal", close, atr_i)


def client_order_id(inst: str, bar_ts: int, side: str) -> str:
    """OKX clOrdId: alphanumeric, ≤32 chars, stable for (inst, bar, side)."""
    digest = hashlib.sha1(f"{inst}|{bar_ts}|{side}".encode()).hexdigest()[:20]
    return f"dc{side[0]}{digest}"


def floor_to_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return int(qty / step + 1e-9) * step


@dataclass(frozen=True)
class Mismatch:
    ccy: str
    bot_qty: float
    exchange_extra: float  # exchange balance minus pre-bot baseline
    critical: bool
    detail: str


def reconcile(sleeves: Mapping[str, Sleeve], balances: Mapping[str, float], baseline: Mapping[str, float],
              tolerances: Mapping[str, float]) -> list[Mismatch]:
    """Bot-owned quantity per base currency must match (balance − baseline) within tolerance.

    Having *more* than expected is a warning (someone added coins); having *less*
    is critical (coins the bot thinks it owns are gone).
    """
    out: list[Mismatch] = []
    for s in sleeves.values():
        ccy = s.base_ccy
        extra = float(balances.get(ccy, 0.0)) - float(baseline.get(ccy, 0.0))
        tol = float(tolerances.get(ccy, 0.0))
        diff = extra - s.qty
        if abs(diff) <= tol:
            continue
        critical = diff < 0
        out.append(Mismatch(ccy, s.qty, extra, critical,
                            f"bot owns {s.qty:.8f} {ccy} but exchange has {extra:.8f} above baseline ({'short' if critical else 'excess'} {abs(diff):.8f})"))
    return out


@dataclass
class Fill:
    side: str
    base_filled: float  # accFillSz
    avg_px: float
    fee: float  # OKX reports fees as negative numbers
    fee_ccy: str


def apply_fill(sleeve: Sleeve, fill: Fill, *, fill_ts: int, decision: Decision) -> dict[str, Any]:
    """Mutates the sleeve and returns a trade record."""
    fee_abs = abs(fill.fee)
    quote = fill.base_filled * fill.avg_px
    realized: float | None = None
    if fill.side == "buy":
        received = fill.base_filled - (fee_abs if fill.fee_ccy == sleeve.base_ccy else 0.0)
        spent = quote + (fee_abs if fill.fee_ccy == "USDT" else 0.0)
        sleeve.cash_usd -= spent
        prev_cost = (sleeve.entry_px or 0.0) * sleeve.qty
        sleeve.qty += received
        sleeve.entry_px = (prev_cost + spent) / sleeve.qty if sleeve.qty > 0 else None
        sleeve.entry_atr = decision.atr
        sleeve.entry_ts = fill_ts
        fee_usd = fee_abs * fill.avg_px if fill.fee_ccy == sleeve.base_ccy else fee_abs
    else:
        proceeds = quote - (fee_abs if fill.fee_ccy == "USDT" else fee_abs * fill.avg_px)
        cost = (sleeve.entry_px or fill.avg_px) * fill.base_filled
        realized = proceeds - cost
        sleeve.realized_pnl_usd += realized
        sleeve.cash_usd += proceeds
        sleeve.qty = max(0.0, sleeve.qty - fill.base_filled)
        if sleeve.qty * fill.avg_px < 1.0:  # dust left after lot rounding
            sleeve.entry_px = sleeve.entry_atr = sleeve.entry_ts = None
        fee_usd = fee_abs if fill.fee_ccy == "USDT" else fee_abs * fill.avg_px
    return {
        "inst": sleeve.inst,
        "side": fill.side,
        "reason": decision.reason,
        "bar_ts": decision.bar_ts,
        "fill_ts": fill_ts,
        "decision_close": decision.close,
        "avg_px": fill.avg_px,
        "base_qty": fill.base_filled,
        "quote_usd": quote,
        "fee_usd": fee_usd,
        "realized_pnl_usd": realized,
    }


def sleeve_equity(sleeve: Sleeve, price: float) -> float:
    return sleeve.cash_usd + sleeve.qty * price
