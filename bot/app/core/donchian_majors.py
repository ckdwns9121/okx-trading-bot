"""Donchian breakout on a few large coins, one independent sleeve per coin — pure logic.

Spec: docs/research/strategy-spec-donchian-majors-2026-10-09.md (pre-registered).

Decision on the confirmed daily close t, fill at the open of t+1, fees per
side. Each sleeve is all-in or all-cash; sleeves never rebalance into each
other. No I/O here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from app.core.indicators import atr_wilder

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Bars:
    inst: str
    ts: list[int]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]


@dataclass(frozen=True)
class DonchianParams:
    entry_days: int = 55
    exit_days: int = 20
    atr_days: int = 20
    atr_stop: float | None = 2.0
    sma_exit_days: int | None = None  # variant ③: also exit when close < SMA(n)
    risk_pct: float | None = None  # v4: size so a hit on the ATR stop loses ~risk_pct of the sleeve

    def warmup(self) -> int:
        return max(self.entry_days, self.exit_days, self.atr_days, self.sma_exit_days or 0) + 1


@dataclass(frozen=True)
class SmaParams:
    sma_days: int = 100


@dataclass
class Trade:
    inst: str
    entry_ts: int
    entry_px: float
    exit_ts: int | None
    exit_px: float | None
    reason: str | None
    pnl_pct: float | None  # net of both fees


# --------------------------------------------------------------------------- #
# Signals (index i = decision bar; uses data up to and including i)
# --------------------------------------------------------------------------- #


def donchian_signal(b: Bars, i: int, in_pos: bool, entry_px: float | None, entry_atr: float | None,
                    atr: Sequence[float | None], p: DonchianParams) -> str:
    if i + 1 < p.warmup():
        return "hold"
    close = b.close[i]
    if not in_pos:
        return "enter" if close > max(b.high[i - p.entry_days : i]) else "hold"
    if close < min(b.low[i - p.exit_days : i]):
        return "exit:channel"
    if p.atr_stop is not None and entry_px is not None and entry_atr is not None and close < entry_px - p.atr_stop * entry_atr:
        return "exit:atr_stop"
    if p.sma_exit_days and close < statistics.fmean(b.close[i + 1 - p.sma_exit_days : i + 1]):
        return "exit:sma"
    return "hold"


def sma_signal(b: Bars, i: int, in_pos: bool, p: SmaParams) -> str:
    if i + 1 < p.sma_days:
        return "hold"
    above = b.close[i] > statistics.fmean(b.close[i + 1 - p.sma_days : i + 1])
    if above and not in_pos:
        return "enter"
    if not above and in_pos:
        return "exit:sma"
    return "hold"


def position_fraction(close: float, atr_value: float | None, p: DonchianParams) -> float:
    """Share of the sleeve to invest on entry. 1.0 = all-in (v3); with risk_pct, turtle-style sizing (v4)."""
    if p.risk_pct is None or atr_value is None or atr_value <= 0 or close <= 0:
        return 1.0
    stop_mult = p.atr_stop if p.atr_stop is not None else 2.0
    return max(0.0, min(1.0, (p.risk_pct / 100.0) / (stop_mult * atr_value / close)))


# --------------------------------------------------------------------------- #
# Sleeve simulation
# --------------------------------------------------------------------------- #


def run_sleeve(b: Bars, *, rule: str, params: DonchianParams | SmaParams, start_ts: int, end_ts: int | None,
               cash: float, fee_pct: float) -> tuple[dict[int, float], list[Trade]]:
    """Returns ({ts: equity at close}, trades). Equity series starts at the first bar ≥ start_ts."""
    fee = fee_pct / 100.0
    atr = atr_wilder(b.high, b.low, b.close, params.atr_days) if isinstance(params, DonchianParams) else []
    qty = 0.0
    entry_px = entry_atr = None
    trades: list[Trade] = []
    pending: str | None = None
    pending_frac = 1.0
    equity: dict[int, float] = {}
    for i, t in enumerate(b.ts):
        if end_ts is not None and t > end_ts:
            break
        live = t >= start_ts
        # 1) execute yesterday's decision at today's open
        if pending and live:
            px = b.open[i]
            if pending == "enter" and qty == 0.0:
                invest = cash * pending_frac
                qty = invest * (1 - fee) / px
                cash -= invest
                entry_px = px
                trades.append(Trade(b.inst, t, px, None, None, None, None))
            elif pending.startswith("exit") and qty > 0.0:
                cash += qty * px * (1 - fee)
                qty = 0.0
                tr = trades[-1]
                tr.exit_ts, tr.exit_px, tr.reason = t, px, pending.split(":", 1)[1]
                tr.pnl_pct = ((px * (1 - fee)) / (tr.entry_px / (1 - fee)) - 1.0) * 100.0
                entry_px = entry_atr = None
        pending = None
        # 2) decide on today's close
        in_pos = qty > 0.0
        if isinstance(params, DonchianParams):
            sig = donchian_signal(b, i, in_pos, entry_px, entry_atr, atr, params)
            if sig == "enter":
                entry_atr = atr[i]
                pending_frac = position_fraction(b.close[i], entry_atr, params)
        else:
            sig = sma_signal(b, i, in_pos, params)
        if live and sig != "hold":
            pending = sig
        if live:
            equity[t] = cash + qty * b.close[i]
    return equity, trades


# --------------------------------------------------------------------------- #
# Portfolio + metrics
# --------------------------------------------------------------------------- #


def perf(ts: Sequence[int], curve: Sequence[float]) -> dict[str, float]:
    if len(curve) < 2:
        return {"cagr_pct": 0.0, "ann_vol_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0}
    years = (ts[-1] - ts[0]) / (365.25 * DAY_MS)
    rets = [curve[k] / curve[k - 1] - 1.0 for k in range(1, len(curve)) if curve[k - 1] > 0]
    sd = statistics.pstdev(rets)
    peak, mdd = -math.inf, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100.0 if peak > 0 else 0.0)
    return {
        "cagr_pct": ((curve[-1] / curve[0]) ** (1 / years) - 1.0) * 100.0 if years > 0 else 0.0,
        "ann_vol_pct": sd * math.sqrt(365.0) * 100.0,
        "sharpe": statistics.fmean(rets) / sd * math.sqrt(365.0) if sd > 0 else 0.0,
        "max_drawdown_pct": mdd,
    }


def _combine(curves: Mapping[str, dict[int, float]], sleeve_cash: float) -> tuple[list[int], list[float]]:
    calendar = sorted(set().union(*[set(c) for c in curves.values()]))
    last = {k: sleeve_cash for k in curves}
    out_ts, out = [], []
    for t in calendar:
        for k, c in curves.items():
            if t in c:
                last[k] = c[t]
        out_ts.append(t)
        out.append(sum(last.values()))
    return out_ts, out


def backtest_portfolio(bars: Mapping[str, Bars], *, rule: str, params: DonchianParams | SmaParams | None,
                       start_ts: int, end_ts: int | None = None, fee_pct: float = 0.15,
                       starting_cash: float = 10_000.0) -> dict[str, Any]:
    """rule: 'donchian' | 'sma' | 'hold'. Equal independent sleeves."""
    sleeve_cash = starting_cash / len(bars)
    curves: dict[str, dict[int, float]] = {}
    trades: list[Trade] = []
    exposure: dict[str, float] = {}
    for inst, b in bars.items():
        if rule == "hold":
            fee = fee_pct / 100.0
            idx = [i for i, t in enumerate(b.ts) if t >= start_ts and (end_ts is None or t <= end_ts)]
            q = sleeve_cash * (1 - fee) / b.open[idx[0]]
            curves[inst] = {b.ts[i]: q * b.close[i] for i in idx}
            exposure[inst] = 100.0
            continue
        eq, tr = run_sleeve(b, rule=rule, params=params, start_ts=start_ts, end_ts=end_ts, cash=sleeve_cash, fee_pct=fee_pct)
        curves[inst] = eq
        trades += tr
        days_in = 0
        for x in tr:
            end = x.exit_ts if x.exit_ts is not None else max(eq)
            days_in += (end - x.entry_ts) / DAY_MS
        span = (max(eq) - min(eq)) / DAY_MS if eq else 1
        exposure[inst] = days_in / span * 100.0 if span > 0 else 0.0
    ts, curve = _combine(curves, sleeve_cash)
    closed = [x for x in trades if x.pnl_pct is not None]
    wins = [x.pnl_pct for x in closed if x.pnl_pct > 0]
    losses = [x.pnl_pct for x in closed if x.pnl_pct <= 0]
    per_inst = {inst: perf(sorted(c), [c[t] for t in sorted(c)]) for inst, c in curves.items()}
    for inst in per_inst:
        n = [x for x in closed if x.inst == inst]
        per_inst[inst]["round_trips"] = len(n)
        per_inst[inst]["exposure_pct"] = exposure[inst]
    return {
        "rule": rule,
        "params": asdict(params) if params is not None else None,
        "fee_pct": fee_pct,
        "from": ts[0], "to": ts[-1],
        "final_equity_usd": curve[-1],
        **perf(ts, curve),
        "round_trips": len(closed),
        "open_positions": [x.inst for x in trades if x.pnl_pct is None],
        "win_rate_pct": len(wins) / len(closed) * 100.0 if closed else 0.0,
        "avg_win_pct": statistics.fmean(wins) if wins else 0.0,
        "avg_loss_pct": statistics.fmean(losses) if losses else 0.0,
        "best_trade_pct": max((x.pnl_pct for x in closed), default=0.0),
        "worst_trade_pct": min((x.pnl_pct for x in closed), default=0.0),
        "per_inst": per_inst,
        "trades": [asdict(x) for x in trades],
        "curve_ts": ts,
        "curve": curve,
        "_daily_returns": [curve[k] / curve[k - 1] - 1.0 for k in range(1, len(curve)) if curve[k - 1] > 0],
    }
