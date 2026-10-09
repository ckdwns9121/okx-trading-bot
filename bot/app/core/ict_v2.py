"""ICT v2: daily bias → 4H FVG / order-block POI → 15m sweep + MSS → LTF FVG/OB entry (long only).

Spec: docs/research/strategy-spec-ict-v2-2026-10-09.md (pre-registered). Pure logic, no I/O.

Modes:
- "full"  (L2): the whole ICT sequence
- "poi"   (L1): buy the POI top on arrival, stop under the POI
Random-entry baseline (L0) lives in ``random_trades``.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, replace
from typing import Sequence

from app.core.ict_reversal import Bars, Costs, TradeResult

M15 = 15 * 60 * 1000
H4 = 4 * 3_600_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class V2Params:
    bias_sma_days: int = 50
    htf_disp_mult: float = 1.5
    poi_max_age_days: int = 30
    discount_lookback_h4: int = 120
    ltf_disp_mult: float = 1.5
    swing_lookback: int = 8
    arm_window: int = 96  # 15m bars after arrival
    entry_window: int = 16
    target_r_min: float = 2.0
    max_hold_bars: int = 288
    stop_buffer_pct: float = 0.05
    min_r_pct: float = 0.15
    max_r_pct: float = 5.0


@dataclass
class Poi:
    kind: str  # "fvg" | "ob"
    bottom: float
    top: float
    active_from: int
    expires: int
    consumed: bool = False
    broken: bool = False


# --------------------------------------------------------------------------- #
# Aggregation & building blocks
# --------------------------------------------------------------------------- #


def aggregate(b: Bars, period_ms: int) -> Bars:
    """Group 15m bars into UTC-aligned buckets (4H, 1D). Only complete-or-partial buckets that exist."""
    ts, o, h, l, c = [], [], [], [], []
    cur = None
    for i, t in enumerate(b.ts):
        bucket = t - t % period_ms
        if bucket != cur:
            cur = bucket
            ts.append(bucket); o.append(b.open[i]); h.append(b.high[i]); l.append(b.low[i]); c.append(b.close[i])
        else:
            h[-1] = max(h[-1], b.high[i]); l[-1] = min(l[-1], b.low[i]); c[-1] = b.close[i]
    return Bars(b.inst + f"@{period_ms}", ts, o, h, l, c)


def daily_bias(d1: Bars, sma: int) -> dict[int, bool]:
    """Day start → long allowed, using closes up to the previous day only."""
    out: dict[int, bool] = {}
    for k in range(sma, len(d1.ts)):
        prev = d1.close[k - sma : k]
        out[d1.ts[k]] = d1.close[k - 1] > statistics.fmean(prev)
    return out


def find_pois(h4: Bars, p: V2Params) -> list[Poi]:
    bodies = [abs(c - o) for o, c in zip(h4.open, h4.close)]
    out: list[Poi] = []
    for k in range(2, len(h4.ts)):
        start = h4.ts[k] + H4
        expires = start + p.poi_max_age_days * DAY_MS
        if h4.high[k - 2] < h4.low[k]:
            out.append(Poi("fvg", h4.high[k - 2], h4.low[k], start, expires))
        if k >= 21:
            med = statistics.median(bodies[k - 20 : k])
            disp = h4.close[k] > h4.open[k] and bodies[k] >= p.htf_disp_mult * med and h4.close[k] > h4.high[k - 1]
            if disp and h4.close[k - 1] < h4.open[k - 1]:
                out.append(Poi("ob", h4.low[k - 1], h4.high[k - 1], start, expires))
    return out


def _net_r(entry: float, exit_px: float, stop: float, c: Costs) -> float:
    fee = c.fee_pct / 100.0
    return (exit_px * (1 - fee) - entry * (1 + fee)) / (entry - stop)


def _walk_exit(b: Bars, i0: int, entry: float, stop: float, target: float, max_hold: int, c: Costs) -> tuple[int, float, str]:
    last = min(len(b.ts) - 1, i0 + max_hold)
    slip = c.stop_slip_pct / 100.0
    for k in range(i0, last + 1):
        if b.low[k] <= stop:
            return k, min(stop, b.open[k]) * (1 - slip), "stop"  # gap through the stop fills at the open
        if k > i0 and b.high[k] >= target:
            return k, target, "target"
    return last, b.close[last] * (1 - slip), "time"


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #


def simulate(b: Bars, p: V2Params, c: Costs, mode: str = "full", pois: list[Poi] | None = None) -> list[TradeResult]:
    """One position at a time. mode "full" = L2 (ICT), "poi" = L1 (buy the zone on arrival)."""
    h4 = aggregate(b, H4)
    d1 = aggregate(b, DAY_MS)
    bias = daily_bias(d1, p.bias_sma_days)
    pois = [replace(x) for x in (pois if pois is not None else find_pois(h4, p))]
    pois.sort(key=lambda x: x.active_from)
    h4_close_at = dict(zip(h4.ts, h4.close))
    h4_index = {t: k for k, t in enumerate(h4.ts)}
    bodies = [abs(cl - op) for op, cl in zip(b.open, b.close)]
    buf = p.stop_buffer_pct / 100.0

    trades: list[TradeResult] = []
    active: list[Poi] = []
    next_poi = 0
    busy_until = -1
    armed: dict | None = None
    pending: dict | None = None

    def range_at(t: int) -> tuple[float, float] | None:
        k = h4_index.get(t - t % H4)
        if k is None or k < p.discount_lookback_h4:
            return None
        return min(h4.low[k - p.discount_lookback_h4 : k]), max(h4.high[k - p.discount_lookback_h4 : k])

    def enter(i: int, entry: float, stop: float, target: float) -> int:
        fill = min(entry, b.open[i])  # a gap below the limit fills at the open
        ex_i, ex_px, why = _walk_exit(b, i, fill, stop, target, p.max_hold_bars, c)
        trades.append(TradeResult(b.inst, "", b.ts[i], b.ts[ex_i], fill, stop, target, ex_px, why,
                                  (fill - stop) / fill * 100.0, _net_r(fill, ex_px, stop, c)))
        return ex_i

    for i, t in enumerate(b.ts):
        if i > 0 and t % H4 == 0:  # a 4H bar just closed
            cl = h4_close_at.get(t - H4)
            if cl is not None:
                for poi in active:
                    if cl < poi.bottom:
                        poi.broken = True
                if armed is not None and cl < armed["poi"].bottom:
                    armed = None
        while next_poi < len(pois) and pois[next_poi].active_from <= t:
            active.append(pois[next_poi]); next_poi += 1
        active = [x for x in active if not (x.consumed or x.broken) and x.expires > t]

        # every touch uses a zone up, even while a trade is open
        touched = [x for x in active if b.low[i] <= x.top]
        for x in touched:
            x.consumed = True
        if i <= busy_until:
            continue

        # ---- resting limit order ----
        if pending is not None:
            if i > pending["deadline"]:
                pending = None
            elif b.low[i] <= pending["entry"]:
                busy_until = enter(i, pending["entry"], pending["stop"], pending["target"])
                pending = None
                continue
            else:
                continue

        # ---- arrival (needs long bias today, a discount zone, a free slot) ----
        if armed is None and touched and i >= p.swing_lookback and bias.get(t - t % DAY_MS, False):
            rng = range_at(t)
            if rng is not None:
                mid = (rng[0] + rng[1]) / 2
                cand = [x for x in touched if x.top <= mid]
                if cand:
                    poi = max(cand, key=lambda x: x.top)
                    if mode == "poi":
                        entry, stop = poi.top, poi.bottom * (1 - buf)
                        if p.min_r_pct <= (entry - stop) / entry * 100.0 <= p.max_r_pct:
                            target = max(entry + p.target_r_min * (entry - stop), rng[1])
                            busy_until = enter(i, entry, stop, target)
                        continue
                    armed = {"poi": poi, "arrival": i, "ref_low": min(b.low[i - p.swing_lookback : i]),
                             "low": b.low[i], "low_i": i, "range_high": rng[1]}
                    continue

        # ---- armed: wait for sweep + MSS + displacement ----
        if armed is None or mode == "poi":
            continue
        if i - armed["arrival"] > p.arm_window:
            armed = None
            continue
        if b.low[i] < armed["low"]:
            armed["low"], armed["low_i"] = b.low[i], i
            continue
        j = armed["low_i"]
        if armed["low"] >= armed["ref_low"] or j < p.swing_lookback:
            continue
        if b.close[i] <= max(b.high[j - p.swing_lookback : j]):
            continue
        med = statistics.median(bodies[max(0, i - 20) : i])
        if not (b.close[i] > b.open[i] and bodies[i] >= p.ltf_disp_mult * med):
            continue
        entry = None
        for k in (i, i - 1):
            if k - 2 >= 0 and b.high[k - 2] < b.low[k]:
                entry = b.low[k]  # top of the bullish FVG
                break
        if entry is None:
            ob = next((k for k in range(i - 1, j - 1, -1) if b.close[k] < b.open[k]), None)
            entry = b.high[ob] if ob is not None else None
        stop = armed["low"] * (1 - buf)
        range_high = armed["range_high"]
        armed = None
        if entry is None or entry <= stop:
            continue
        if not (p.min_r_pct <= (entry - stop) / entry * 100.0 <= p.max_r_pct):
            continue
        target = max(entry + p.target_r_min * (entry - stop), range_high)
        pending = {"entry": entry, "stop": stop, "target": target, "deadline": i + p.entry_window}
    return trades


def random_trades(b: Bars, n: int, sample: Sequence[TradeResult], p: V2Params, c: Costs, rng: random.Random) -> list[TradeResult]:
    """Random 15m entries on long-bias days; R distance and target multiple drawn from the real trades."""
    if not sample or n == 0:
        return []
    d1 = aggregate(b, DAY_MS)
    bias = daily_bias(d1, p.bias_sma_days)
    cand = [i for i, t in enumerate(b.ts) if bias.get(t - t % DAY_MS, False)]
    if not cand:
        return []
    shapes = [(s.r_pct, (s.target - s.entry) / (s.entry - s.stop)) for s in sample]
    out: list[TradeResult] = []
    for _ in range(n):
        i = rng.choice(cand)
        r_pct, tgt_r = rng.choice(shapes)
        entry = b.open[i]
        stop = entry * (1 - r_pct / 100.0)
        target = entry + tgt_r * (entry - stop)
        ex_i, ex_px, why = _walk_exit(b, i, entry, stop, target, p.max_hold_bars, c)
        out.append(TradeResult(b.inst, "", b.ts[i], b.ts[ex_i], entry, stop, target, ex_px, why, r_pct, _net_r(entry, ex_px, stop, c)))
    return out
