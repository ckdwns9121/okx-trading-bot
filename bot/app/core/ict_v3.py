"""ICT v3: buy a 4H demand zone on 15m bullish RSI divergence, sell at the nearest 4H supply zone
on bearish divergence (long only).

Spec: docs/research/strategy-spec-ict-v3-2026-10-09.md (pre-registered). Pure logic, no I/O.

entry modes: "div" (bullish divergence) | "zone" (zone top on arrival)
exit modes:  "div" (bearish divergence after reaching the supply zone) | "touch" (limit at the zone bottom)
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, replace
from typing import Sequence

from app.core.ict_reversal import Bars, Costs, TradeResult
from app.core.ict_v2 import DAY_MS, H4, Poi, V2Params, aggregate, find_pois


@dataclass(frozen=True)
class V3Params:
    rsi_len: int = 14
    pivot_w: int = 3
    div_min_gap: int = 5
    div_max_gap: int = 48
    htf_disp_mult: float = 1.5
    zone_max_age_days: int = 30
    arm_window: int = 96
    max_hold_bars: int = 480
    min_rr: float = 1.0
    stop_buffer_pct: float = 0.05
    min_r_pct: float = 0.15
    max_r_pct: float = 5.0


# --------------------------------------------------------------------------- #
# Zones
# --------------------------------------------------------------------------- #


def demand_zones(h4: Bars, p: V3Params) -> list[Poi]:
    return find_pois(h4, V2Params(htf_disp_mult=p.htf_disp_mult, poi_max_age_days=p.zone_max_age_days))


def supply_zones(h4: Bars, p: V3Params) -> list[Poi]:
    bodies = [abs(c - o) for o, c in zip(h4.open, h4.close)]
    out: list[Poi] = []
    for k in range(2, len(h4.ts)):
        start = h4.ts[k] + H4
        expires = start + p.zone_max_age_days * DAY_MS
        if h4.low[k - 2] > h4.high[k]:
            out.append(Poi("fvg", h4.high[k], h4.low[k - 2], start, expires))
        if k >= 21:
            med = statistics.median(bodies[k - 20 : k])
            disp = h4.close[k] < h4.open[k] and bodies[k] >= p.htf_disp_mult * med and h4.close[k] < h4.low[k - 1]
            if disp and h4.close[k - 1] > h4.open[k - 1]:
                out.append(Poi("ob", h4.low[k - 1], h4.high[k - 1], start, expires))
    return out


# --------------------------------------------------------------------------- #
# RSI & divergence (confirmed w bars after the pivot — no lookahead)
# --------------------------------------------------------------------------- #


def rsi(close: Sequence[float], n: int) -> list[float]:
    out = [50.0] * len(close)
    if len(close) <= n:
        return out
    gains = [max(close[k] - close[k - 1], 0.0) for k in range(1, n + 1)]
    losses = [max(close[k - 1] - close[k], 0.0) for k in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    for k in range(n, len(close)):
        if k > n:
            ch = close[k] - close[k - 1]
            ag = (ag * (n - 1) + max(ch, 0.0)) / n
            al = (al * (n - 1) + max(-ch, 0.0)) / n
        out[k] = 50.0 if ag == al == 0 else 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def divergences(b: Bars, p: V3Params) -> tuple[list[int | None], list[int | None]]:
    """bull[i] / bear[i] = pivot index p2 of a divergence confirmed at bar i, else None."""
    r = rsi(b.close, p.rsi_len)
    w = p.pivot_w
    n = len(b.ts)
    bull: list[int | None] = [None] * n
    bear: list[int | None] = [None] * n
    lows: list[int] = []
    highs: list[int] = []
    for i in range(2 * w, n):
        q = i - w
        if q < p.rsi_len:
            continue
        if b.low[q] < min(b.low[q - w : q]) and b.low[q] <= min(b.low[q + 1 : i + 1]):
            prev = next((x for x in reversed(lows) if p.div_min_gap <= q - x <= p.div_max_gap), None)
            if prev is not None and b.low[q] < b.low[prev] and r[q] > r[prev]:
                bull[i] = q
            lows.append(q)
        if b.high[q] > max(b.high[q - w : q]) and b.high[q] >= max(b.high[q + 1 : i + 1]):
            prev = next((x for x in reversed(highs) if p.div_min_gap <= q - x <= p.div_max_gap), None)
            if prev is not None and b.high[q] > b.high[prev] and r[q] < r[prev]:
                bear[i] = q
            highs.append(q)
    return bull, bear


# --------------------------------------------------------------------------- #
# Exits
# --------------------------------------------------------------------------- #


def _net_r(entry: float, exit_px: float, stop: float, c: Costs) -> float:
    fee = c.fee_pct / 100.0
    return (exit_px * (1 - fee) - entry * (1 + fee)) / (entry - stop)


def walk_exit(b: Bars, i0: int, stop: float, target: float, max_hold: int, c: Costs, mode: str,
              bear: Sequence[int | None]) -> tuple[int, float, str]:
    slip = c.stop_slip_pct / 100.0
    last = min(len(b.ts) - 1, i0 + max_hold)
    reached = None
    for k in range(i0, last + 1):
        if b.low[k] <= stop:
            return k, min(stop, b.open[k]) * (1 - slip), "stop"
        if k == i0:
            continue
        if mode == "touch":
            if b.high[k] >= target:
                return k, max(target, b.open[k]), "target"
        else:
            if reached is None and b.high[k] >= target:
                reached = k
            q = bear[k]
            if reached is not None and q is not None and q >= reached and k + 1 < len(b.ts):
                return k + 1, b.open[k + 1] * (1 - slip), "div"
    return last, b.close[last] * (1 - slip), "time"


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #


def simulate(b: Bars, p: V3Params, c: Costs, entry_mode: str = "div", exit_mode: str = "div",
             zones: tuple[list[Poi], list[Poi]] | None = None,
             divs: tuple[list[int | None], list[int | None]] | None = None) -> list[TradeResult]:
    if zones is None:
        h4 = aggregate(b, H4)
        zones = (demand_zones(h4, p), supply_zones(h4, p))
    h4c = aggregate(b, H4)
    close_at = dict(zip(h4c.ts, h4c.close))
    bull, bear = divs if divs is not None else divergences(b, p)
    demand = sorted((replace(z) for z in zones[0]), key=lambda z: z.active_from)
    supply = sorted((replace(z) for z in zones[1]), key=lambda z: z.active_from)
    buf = p.stop_buffer_pct / 100.0
    slip = c.stop_slip_pct / 100.0

    trades: list[TradeResult] = []
    act_d: list[Poi] = []
    act_s: list[Poi] = []
    nd = ns = 0
    busy_until = -1
    armed: dict | None = None

    def try_enter(i: int, entry: float, stop: float) -> int | None:
        if entry <= stop or not (p.min_r_pct <= (entry - stop) / entry * 100.0 <= p.max_r_pct):
            return None
        above = [z.bottom for z in act_s if z.bottom > entry]
        if not above:
            return None
        target = min(above)
        if target - entry < p.min_rr * (entry - stop):
            return None
        ex_i, ex_px, why = walk_exit(b, i, stop, target, p.max_hold_bars, c, exit_mode, bear)
        trades.append(TradeResult(b.inst, "", b.ts[i], b.ts[ex_i], entry, stop, target, ex_px, why,
                                  (entry - stop) / entry * 100.0, _net_r(entry, ex_px, stop, c)))
        return ex_i

    for i, t in enumerate(b.ts):
        if i > 0 and t % H4 == 0:
            cl = close_at.get(t - H4)
            if cl is not None:
                for z in act_d:
                    if cl < z.bottom:
                        z.broken = True
                for z in act_s:
                    if cl > z.top:
                        z.broken = True
                if armed is not None and cl < armed["zone"].bottom:
                    armed = None
        while nd < len(demand) and demand[nd].active_from <= t:
            act_d.append(demand[nd]); nd += 1
        while ns < len(supply) and supply[ns].active_from <= t:
            act_s.append(supply[ns]); ns += 1
        act_d = [z for z in act_d if not (z.consumed or z.broken) and z.expires > t]
        act_s = [z for z in act_s if not z.broken and z.expires > t]

        touched = [z for z in act_d if b.low[i] <= z.top]
        for z in touched:
            z.consumed = True
        if i <= busy_until:
            continue

        if armed is None and touched:
            zone = max(touched, key=lambda z: z.top)
            if entry_mode == "zone":
                ex = try_enter(i, min(zone.top, b.open[i]), zone.bottom * (1 - buf))
                if ex is not None:
                    busy_until = ex
                continue
            armed = {"zone": zone, "arrival": i}

        if armed is None:
            continue
        if i - armed["arrival"] > p.arm_window:
            armed = None
            continue
        q = bull[i]
        if q is None or q < armed["arrival"] or b.low[q] > armed["zone"].top or i + 1 >= len(b.ts):
            continue
        stop = min(armed["zone"].bottom, b.low[q]) * (1 - buf)
        armed = None
        ex = try_enter(i + 1, b.open[i + 1] * (1 + slip), stop)
        if ex is not None:
            busy_until = ex
    return trades


def random_trades(b: Bars, n: int, sample: Sequence[TradeResult], p: V3Params, c: Costs,
                  rng: random.Random) -> list[TradeResult]:
    if not sample or n == 0:
        return []
    shapes = [(s.r_pct, (s.target - s.entry) / (s.entry - s.stop)) for s in sample]
    out: list[TradeResult] = []
    for _ in range(n):
        i = rng.randrange(p.rsi_len, len(b.ts) - 1)
        r_pct, tgt_r = rng.choice(shapes)
        entry = b.open[i]
        stop = entry * (1 - r_pct / 100.0)
        target = entry + tgt_r * (entry - stop)
        ex_i, ex_px, why = walk_exit(b, i, stop, target, p.max_hold_bars, c, "touch", [])
        out.append(TradeResult(b.inst, "", b.ts[i], b.ts[ex_i], entry, stop, target, ex_px, why, r_pct,
                               _net_r(entry, ex_px, stop, c)))
    return out
