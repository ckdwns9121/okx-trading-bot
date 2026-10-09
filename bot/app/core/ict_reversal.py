"""ICT reversal model on intraday bars (long only) — pure logic.

Spec: docs/research/strategy-spec-ict-reversal-2026-10-09.md (pre-registered).

Pipeline per UTC day: prior-day low (liquidity) → killzone sweep → market
structure shift with displacement → bullish FVG → limit entry at the FVG
midpoint → stop under the sweep low, target at k·R, flat at the day's last
bar. Conservative fills: stop wins any same-bar tie. Also a random-entry
bracket baseline that keeps everything except the ICT conditions.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

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
class IctParams:
    swing_lookback: int = 8  # bars before the sweep that define the reference high
    mss_window: int = 12  # bars after the sweep to see the structure shift
    displacement_mult: float = 1.5  # MSS body ≥ mult × median body of last 20 bars
    entry_window: int = 8  # bars after MSS for the limit at the FVG midpoint to fill
    target_r: float = 2.0
    stop_buffer_pct: float = 0.05
    min_r_pct: float = 0.15
    max_r_pct: float = 3.0
    killzones_utc: tuple[tuple[int, int], ...] = ((7, 10), (12, 15))


@dataclass(frozen=True)
class Costs:
    fee_pct: float = 0.10  # per side, every fill
    stop_slip_pct: float = 0.05  # market exits only


@dataclass
class TradeResult:
    inst: str
    day: str
    entry_ts: int
    exit_ts: int
    entry: float
    stop: float
    target: float
    exit: float
    exit_reason: str  # "target" | "stop" | "eod"
    r_pct: float  # (entry − stop) / entry, in %
    r_multiple: float  # net of costs, in units of R

    def net_return_pct(self) -> float:
        return self.r_multiple * self.r_pct


def _hour(ts_ms: int) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).hour


def _day(ts_ms: int) -> int:
    return ts_ms - ts_ms % DAY_MS


def in_killzone(ts_ms: int, zones: Sequence[tuple[int, int]]) -> bool:
    h = _hour(ts_ms)
    return any(a <= h < b for a, b in zones)


def day_index(b: Bars) -> dict[int, tuple[int, int]]:
    """UTC day start → (first bar index, last bar index)."""
    out: dict[int, list[int]] = {}
    for i, t in enumerate(b.ts):
        d = _day(t)
        if d not in out:
            out[d] = [i, i]
        out[d][1] = i
    return {d: (a, z) for d, (a, z) in out.items()}


def _exit_after_entry(b: Bars, entry_i: int, last_i: int, entry: float, stop: float, target: float,
                      costs: Costs) -> tuple[int, float, str]:
    """Walk bars from the entry bar; stop wins same-bar ties. Returns (exit index, gross exit px, reason)."""
    for k in range(entry_i, last_i + 1):
        if b.low[k] <= stop:
            return k, stop * (1 - costs.stop_slip_pct / 100.0), "stop"
        if k > entry_i and b.high[k] >= target:  # entry bar: price came down to fill; don't credit an up-move inside it
            return k, target, "target"
    return last_i, b.close[last_i] * (1 - costs.stop_slip_pct / 100.0), "eod"


def _net_r(entry: float, exit_px: float, stop: float, costs: Costs) -> float:
    fee = costs.fee_pct / 100.0
    net = exit_px * (1 - fee) - entry * (1 + fee)
    return net / (entry - stop)


def find_setups(b: Bars, p: IctParams, costs: Costs) -> list[TradeResult]:
    days = day_index(b)
    order = sorted(days)
    trades: list[TradeResult] = []
    bodies = [abs(c - o) for o, c in zip(b.open, b.close)]
    for di in range(1, len(order)):
        prev_a, prev_z = days[order[di - 1]]
        a, z = days[order[di]]
        if order[di] - order[di - 1] != DAY_MS:
            continue
        pdl = min(b.low[prev_a : prev_z + 1])
        # first bar of the day that takes the PDL, must be inside a killzone
        sweep_i = next((i for i in range(a, z + 1) if b.low[i] < pdl), None)
        if sweep_i is None or not in_killzone(b.ts[sweep_i], p.killzones_utc) or sweep_i - p.swing_lookback < 0:
            continue
        ref_high = max(b.high[sweep_i - p.swing_lookback : sweep_i])
        mss_i = None
        for j in range(sweep_i, min(z, sweep_i + p.mss_window) + 1):
            if b.close[j] > ref_high:
                med = statistics.median(bodies[max(0, j - 20) : j]) if j >= 2 else bodies[j]
                if b.close[j] > b.open[j] and bodies[j] >= p.displacement_mult * med:
                    mss_i = j
                break  # first close above the reference decides; weak breaks don't get a second chance
        if mss_i is None:
            continue
        sweep_low = min(b.low[sweep_i : mss_i + 1])
        fvg = None
        for k in (mss_i, mss_i - 1):
            if k - 2 >= 0 and b.high[k - 2] < b.low[k]:
                fvg = (b.high[k - 2], b.low[k])
                break
        if fvg is None:
            continue
        entry = (fvg[0] + fvg[1]) / 2.0
        stop = sweep_low * (1 - p.stop_buffer_pct / 100.0)
        if entry <= stop:
            continue
        r_pct = (entry - stop) / entry * 100.0
        if not (p.min_r_pct <= r_pct <= p.max_r_pct):
            continue
        target = entry + p.target_r * (entry - stop)
        entry_i = next((k for k in range(mss_i + 1, min(z, mss_i + p.entry_window) + 1) if b.low[k] <= entry), None)
        if entry_i is None:
            continue
        exit_i, exit_px, reason = _exit_after_entry(b, entry_i, z, entry, stop, target, costs)
        trades.append(TradeResult(b.inst, datetime.fromtimestamp(order[di] / 1000, timezone.utc).strftime("%Y-%m-%d"),
                                  b.ts[entry_i], b.ts[exit_i], entry, stop, target, exit_px, reason, r_pct,
                                  _net_r(entry, exit_px, stop, costs)))
    return trades


def random_bracket_trades(b: Bars, n: int, r_pcts: Sequence[float], p: IctParams, costs: Costs, rng: random.Random) -> list[TradeResult]:
    """Same count, killzone entries at a random bar's open, R distance drawn from the real trades."""
    days = day_index(b)
    candidates = [i for i, t in enumerate(b.ts) if in_killzone(t, p.killzones_utc)]
    if not candidates or not r_pcts:
        return []
    out: list[TradeResult] = []
    used_days: set[int] = set()
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        i = rng.choice(candidates)
        d = _day(b.ts[i])
        if d in used_days:
            continue
        used_days.add(d)
        z = days[d][1]
        entry = b.open[i]
        r_pct = rng.choice(r_pcts)
        stop = entry * (1 - r_pct / 100.0)
        target = entry + p.target_r * (entry - stop)
        exit_i, exit_px, reason = _exit_after_entry(b, i, z, entry, stop, target, costs)
        out.append(TradeResult(b.inst, "", b.ts[i], b.ts[exit_i], entry, stop, target, exit_px, reason, r_pct,
                               _net_r(entry, exit_px, stop, costs)))
    return out


def r_stats(trades: Sequence[TradeResult]) -> dict[str, float]:
    rs = [t.r_multiple for t in trades]
    if len(rs) < 2:
        return {"n": len(rs), "mean_r": rs[0] if rs else 0.0, "t": 0.0, "win_rate_pct": 0.0}
    sd = statistics.stdev(rs)
    return {
        "n": len(rs),
        "mean_r": statistics.fmean(rs),
        "t": statistics.fmean(rs) / (sd / math.sqrt(len(rs))) if sd > 0 else 0.0,
        "win_rate_pct": sum(1 for r in rs if r > 0) / len(rs) * 100.0,
        "target_pct": sum(1 for t in trades if t.exit_reason == "target") / len(rs) * 100.0,
        "stop_pct": sum(1 for t in trades if t.exit_reason == "stop") / len(rs) * 100.0,
        "eod_pct": sum(1 for t in trades if t.exit_reason == "eod") / len(rs) * 100.0,
        "median_r_pct": statistics.median(t.r_pct for t in trades),
    }


def portfolio_curve(trades_by_inst: dict[str, list[TradeResult]], *, sleeve_usd: float, risk_pct: float,
                    start_ts: int, end_ts: int) -> tuple[list[int], list[float]]:
    """Daily equity: each sleeve risks risk_pct of its equity per trade (notional capped at the sleeve)."""
    days = list(range(start_ts - start_ts % DAY_MS, end_ts + DAY_MS, DAY_MS))
    total = [0.0] * len(days)
    for inst, trades in trades_by_inst.items():
        eq = sleeve_usd
        by_exit_day: dict[int, list[TradeResult]] = {}
        for t in trades:
            by_exit_day.setdefault(_day(t.exit_ts), []).append(t)
        for k, d in enumerate(days):
            for t in by_exit_day.get(d, []):
                frac = min(1.0, (risk_pct / 100.0) / (t.r_pct / 100.0))
                eq *= 1 + frac * t.net_return_pct() / 100.0
            total[k] += eq
    return days, total


def perf(ts: Sequence[int], curve: Sequence[float]) -> dict[str, float]:
    if len(curve) < 2 or curve[0] <= 0:
        return {"cagr_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0}
    years = (ts[-1] - ts[0]) / (365.25 * DAY_MS)
    rets = [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve))]
    sd = statistics.pstdev(rets)
    peak, mdd = -math.inf, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100.0)
    return {
        "cagr_pct": ((curve[-1] / curve[0]) ** (1 / years) - 1) * 100.0 if years > 0 else 0.0,
        "sharpe": statistics.fmean(rets) / sd * math.sqrt(365.0) if sd > 0 else 0.0,
        "max_drawdown_pct": mdd,
    }


def trades_to_dicts(trades: Sequence[TradeResult]) -> list[dict[str, Any]]:
    return [asdict(t) for t in trades]
