"""Cross-sectional momentum on OKX spot, weekly rebalance — pure logic.

Spec: docs/research/strategy-spec-xs-momentum-2026-10-04.md (pre-registered).

Everything here is deterministic and I/O free. A ``Series`` is one
instrument's ascending daily candles aligned to a shared UTC calendar; the
backtest decides on Sunday's close and fills at Monday's open, so no
decision ever sees the bar it trades on.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

DAY_MS = 86_400_000
EULER_GAMMA = 0.5772156649


@dataclass(frozen=True)
class XsMomentumParams:
    universe_size: int = 30
    volume_lookback_days: int = 30
    min_history_days: int = 180
    ret_short_days: int = 14
    ret_long_days: int = 28
    vol_window_days: int = 28
    top_n: int = 5
    max_weight: float = 0.25
    target_vol: float | None = 0.25  # annualised; None disables vol targeting
    regime_sma_days: int = 100
    rebalance_band: float = 0.20  # relative deviation that triggers a trade
    min_trade_usd: float = 25.0
    # ---- v2 (spec strategy-spec-xs-momentum-v2) ----
    btc_default: bool = False  # hold BTC with whatever is not allocated to alts
    relative_to_btc: bool = False  # alts need momentum above BTC's to qualify
    max_alts: int = 4
    entry_rank: int = 5  # buy only if ranked within this
    exit_rank: int = 10  # keep while ranked within this
    alt_total_cap: float = 0.80  # alts together never exceed this (BTC keeps the rest)

    def warmup_days(self) -> int:
        return max(
            self.volume_lookback_days,
            self.min_history_days,
            self.ret_long_days,
            self.vol_window_days,
            self.regime_sma_days,
        ) + 1


@dataclass(frozen=True)
class CostModel:
    fee_pct_per_side: float = 0.15  # taker 0.10% + slippage 0.05%


@dataclass
class Series:
    inst: str
    ts: list[int]  # UTC midnight ms, ascending
    open: list[float]
    close: list[float]
    quote_volume: list[float]
    index: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.index = {t: i for i, t in enumerate(self.ts)}

    def at(self, t: int) -> int | None:
        return self.index.get(t)


# --------------------------------------------------------------------------- #
# Calendar helpers
# --------------------------------------------------------------------------- #


def build_calendar(series: Mapping[str, Series]) -> list[int]:
    """Union of all timestamps, ascending."""
    seen: set[int] = set()
    for s in series.values():
        seen.update(s.ts)
    return sorted(seen)


def is_monday(ts_ms: int) -> bool:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).weekday() == 0


def _closes_upto(s: Series, t: int, n: int) -> list[float] | None:
    """Last n closes ending at timestamp t (inclusive), or None if not enough history."""
    i = s.at(t)
    if i is None or i + 1 < n:
        return None
    return s.close[i + 1 - n : i + 1]


# --------------------------------------------------------------------------- #
# Pure building blocks
# --------------------------------------------------------------------------- #


def select_universe(series: Mapping[str, Series], t: int, params: XsMomentumParams) -> list[str]:
    """Top-N by trailing average quote volume, using only data up to t."""
    ranked: list[tuple[float, str]] = []
    for inst, s in series.items():
        i = s.at(t)
        if i is None or i + 1 < params.min_history_days:
            continue
        window = s.quote_volume[i + 1 - params.volume_lookback_days : i + 1]
        if len(window) < params.volume_lookback_days:
            continue
        avg = statistics.fmean(window)
        if avg > 0:
            ranked.append((avg, inst))
    ranked.sort(reverse=True)
    return [inst for _, inst in ranked[: params.universe_size]]


def annualized_vol(closes: Sequence[float]) -> float | None:
    if len(closes) < 3:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * math.sqrt(365.0)


def momentum_score(closes: Sequence[float], params: XsMomentumParams) -> float | None:
    """mean(ret_short, ret_long) / vol — all windows end at the last element."""
    need = max(params.ret_long_days, params.vol_window_days) + 1
    if len(closes) < need:
        return None
    last = closes[-1]
    r_s = last / closes[-1 - params.ret_short_days] - 1.0
    r_l = last / closes[-1 - params.ret_long_days] - 1.0
    vol = annualized_vol(closes[-params.vol_window_days - 1 :])
    if vol is None or vol <= 0:
        return None
    return ((r_s + r_l) / 2.0) / vol


def regime_on(btc_closes: Sequence[float], sma_days: int) -> bool:
    if len(btc_closes) < sma_days:
        return False
    sma = statistics.fmean(btc_closes[-sma_days:])
    return btc_closes[-1] > sma


def _covariance(returns: Sequence[Sequence[float]]) -> list[list[float]]:
    n = len(returns)
    means = [statistics.fmean(r) for r in returns]
    cov = [[0.0] * n for _ in range(n)]
    length = len(returns[0])
    for a in range(n):
        for b in range(a, n):
            c = sum((returns[a][k] - means[a]) * (returns[b][k] - means[b]) for k in range(length)) / length
            cov[a][b] = cov[b][a] = c
    return cov


def target_weights(
    vols: Mapping[str, float],
    returns: Mapping[str, Sequence[float]] | None,
    params: XsMomentumParams,
) -> dict[str, float]:
    """Inverse-vol weights, capped per name, then scaled down to the vol target (never up)."""
    if not vols:
        return {}
    inv = {k: 1.0 / v for k, v in vols.items() if v > 0}
    total = sum(inv.values())
    w = {k: v / total for k, v in inv.items()}

    # cap with redistribution; leftover stays cash
    for _ in range(len(w)):
        over = {k: v - params.max_weight for k, v in w.items() if v > params.max_weight + 1e-12}
        if not over:
            break
        excess = sum(over.values())
        for k in over:
            w[k] = params.max_weight
        under = [k for k, v in w.items() if v < params.max_weight - 1e-12]
        if not under:
            break
        share = sum(w[k] for k in under)
        for k in under:
            w[k] += excess * (w[k] / share) if share > 0 else excess / len(under)

    # portfolio vol target (annualised), using the covariance of daily log returns
    if params.target_vol is not None and returns and len(returns) == len(w) and all(len(returns[k]) >= 5 for k in w):
        keys = list(w)
        cov = _covariance([returns[k] for k in keys])
        var = 0.0
        for a, ka in enumerate(keys):
            for b, kb in enumerate(keys):
                var += w[ka] * w[kb] * cov[a][b]
        port_vol = math.sqrt(max(var, 0.0) * 365.0)
        if params.target_vol is not None and port_vol > params.target_vol > 0:
            scale = params.target_vol / port_vol
            w = {k: v * scale for k, v in w.items()}
    return w


def _v2_targets(
    scored: list[tuple[float, str]],
    vols: Mapping[str, float],
    rets: Mapping[str, list[float]],
    held_alts: Sequence[str],
    series: Mapping[str, Series],
    decision_t: int,
    btc_inst: str,
    params: XsMomentumParams,
) -> dict[str, float]:
    """BTC-default book with relative-momentum alt rotation and rank buffers (spec v2 §4)."""
    need = params.ret_long_days + 1
    btc_closes = _closes_upto(series[btc_inst], decision_t, need)
    if btc_closes is None:
        return {btc_inst: 1.0}
    btc_mom = (btc_closes[-1] / btc_closes[-1 - params.ret_short_days] - 1.0 + btc_closes[-1] / btc_closes[-1 - params.ret_long_days] - 1.0) / 2.0

    def rel_mom(inst: str) -> float | None:
        closes = _closes_upto(series[inst], decision_t, need)
        if closes is None:
            return None
        mom = (closes[-1] / closes[-1 - params.ret_short_days] - 1.0 + closes[-1] / closes[-1 - params.ret_long_days] - 1.0) / 2.0
        return mom - btc_mom

    # candidates: positive score (already filtered upstream), positive relative momentum, not BTC
    ranked: list[str] = []
    for _, inst in scored:
        if inst == btc_inst:
            continue
        if params.relative_to_btc:
            r = rel_mom(inst)
            if r is None or r <= 0:
                continue
        ranked.append(inst)
    rank = {inst: i + 1 for i, inst in enumerate(ranked)}

    keep = [a for a in held_alts if a in rank and rank[a] <= params.exit_rank]
    new = [a for a in ranked if a not in keep and rank[a] <= params.entry_rank]
    alts = (keep + new)[: params.max_alts]
    # if more kept than allowed, drop the worst-ranked
    alts.sort(key=lambda a: rank[a])
    alts = alts[: params.max_alts]

    if not alts:
        return {btc_inst: 1.0}
    inv = {a: 1.0 / vols[a] for a in alts if vols.get(a, 0) > 0}
    total = sum(inv.values())
    w = {a: v / total * params.alt_total_cap for a, v in inv.items()}
    for _ in range(len(w)):
        over = {a: v - params.max_weight for a, v in w.items() if v > params.max_weight + 1e-12}
        if not over:
            break
        for a in over:
            w[a] = params.max_weight
    alt_sum = sum(w.values())
    w[btc_inst] = max(0.0, 1.0 - alt_sum)
    return w


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #


@dataclass
class Trade:
    ts: int
    inst: str
    side: str
    qty: float
    price: float
    notional: float
    fee: float
    kind: str  # "enter" | "exit" | "rebalance"


def _max_drawdown(curve: Sequence[float]) -> tuple[float, int]:
    """Returns (max drawdown pct, longest drawdown length in points)."""
    peak = -math.inf
    mdd = 0.0
    longest = 0
    cur = 0
    for v in curve:
        if v >= peak:
            peak = v
            cur = 0
        else:
            cur += 1
            longest = max(longest, cur)
            if peak > 0:
                mdd = max(mdd, (peak - v) / peak * 100.0)
    return mdd, longest


def _perf(curve_ts: Sequence[int], curve: Sequence[float]) -> dict[str, Any]:
    if len(curve) < 2:
        return {"cagr_pct": 0.0, "ann_vol_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0, "max_drawdown_days": 0}
    years = (curve_ts[-1] - curve_ts[0]) / (365.25 * DAY_MS)
    rets = [curve[i] / curve[i - 1] - 1.0 for i in range(1, len(curve)) if curve[i - 1] > 0]
    mean = statistics.fmean(rets)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    cagr = (curve[-1] / curve[0]) ** (1 / years) - 1.0 if years > 0 and curve[0] > 0 else 0.0
    mdd, mdd_len = _max_drawdown(curve)
    return {
        "cagr_pct": cagr * 100.0,
        "ann_vol_pct": sd * math.sqrt(365.0) * 100.0,
        "sharpe": (mean / sd * math.sqrt(365.0)) if sd > 0 else 0.0,
        "max_drawdown_pct": mdd,
        "max_drawdown_days": mdd_len,
        "daily_returns": rets,
    }


def _portfolio_value(cash: float, holdings: Mapping[str, float], series: Mapping[str, Series], t: int, last_px: dict[str, float]) -> float:
    value = cash
    for inst, qty in holdings.items():
        s = series[inst]
        i = s.at(t)
        if i is not None:
            last_px[inst] = s.close[i]
        value += qty * last_px.get(inst, 0.0)
    return value


def backtest_xs_momentum(
    series: Mapping[str, Series],
    *,
    params: XsMomentumParams = XsMomentumParams(),
    cost: CostModel = CostModel(),
    btc_inst: str = "BTC-USDT",
    starting_cash: float = 10_000.0,
    start_ts: int | None = None,
    end_ts: int | None = None,
    with_benchmarks: bool = True,
) -> dict[str, Any]:
    if btc_inst not in series:
        raise ValueError(f"{btc_inst} series is required for the regime filter")
    calendar = build_calendar(series)
    if start_ts is not None:
        calendar = [t for t in calendar if t >= start_ts]
    if end_ts is not None:
        calendar = [t for t in calendar if t <= end_ts]
    btc = series[btc_inst]
    fee = cost.fee_pct_per_side / 100.0

    cash = starting_cash
    holdings: dict[str, float] = {}
    last_px: dict[str, float] = {}
    trades: list[Trade] = []
    curve_ts: list[int] = []
    curve: list[float] = []
    regime_log: list[tuple[int, bool]] = []
    rebalances = 0
    entries = 0
    turnover_notional = 0.0
    weekly_weights: list[dict[str, Any]] = []

    # benchmark state
    bh_qty: float | None = None
    bh_curve: list[float] = []
    ew_cash = starting_cash
    ew_holdings: dict[str, float] = {}
    ew_curve: list[float] = []
    ew_last_px: dict[str, float] = {}

    first_decision_done = False
    for idx, t in enumerate(calendar):
        if idx == 0:
            continue
        decision_t = calendar[idx - 1]  # yesterday's close is the latest confirmed bar
        warm = btc.at(decision_t)
        if warm is None or warm + 1 < params.warmup_days():
            continue

        if is_monday(t):
            btc_closes = _closes_upto(btc, decision_t, params.regime_sma_days)
            on = regime_on(btc_closes or [], params.regime_sma_days)
            regime_log.append((t, on))
            universe = select_universe(series, decision_t, params)
            held_alts = [k for k in holdings if k != btc_inst]

            target: dict[str, float] = {}
            if on and universe:
                scored: list[tuple[float, str]] = []
                vols: dict[str, float] = {}
                rets: dict[str, list[float]] = {}
                need = max(params.ret_long_days, params.vol_window_days) + 1
                for inst in universe:
                    closes = _closes_upto(series[inst], decision_t, need)
                    if closes is None:
                        continue
                    sc = momentum_score(closes, params)
                    if sc is None or sc <= 0:
                        continue
                    vol = annualized_vol(closes[-params.vol_window_days - 1 :])
                    if vol is None or vol <= 0:
                        continue
                    scored.append((sc, inst))
                    vols[inst] = vol
                    win = closes[-params.vol_window_days - 1 :]
                    rets[inst] = [math.log(win[k] / win[k - 1]) for k in range(1, len(win))]
                scored.sort(reverse=True)
                if params.btc_default:
                    target = _v2_targets(scored, vols, rets, held_alts, series, decision_t, btc_inst, params)
                else:
                    picks = [inst for _, inst in scored[: params.top_n]]
                    target = target_weights({k: vols[k] for k in picks}, {k: rets[k] for k in picks}, params)

            # ---- execute at today's open with band logic ----
            equity = _portfolio_value(cash, holdings, series, decision_t, last_px)
            # sells first (exits and trims), then buys
            for inst in list(holdings):
                s = series[inst]
                i = s.at(t)
                if i is None:
                    continue  # no bar today; keep until it trades again
                px = s.open[i]
                cur_w = holdings[inst] * px / equity if equity > 0 else 0.0
                tgt_w = target.get(inst, 0.0)
                if tgt_w == 0.0:
                    qty = holdings.pop(inst)
                    notional = qty * px
                    f = notional * fee
                    cash += notional - f
                    trades.append(Trade(t, inst, "sell", qty, px, notional, f, "exit"))
                    turnover_notional += notional
                elif cur_w > tgt_w and (cur_w - tgt_w) / tgt_w > params.rebalance_band:
                    delta_w = cur_w - tgt_w
                    qty = delta_w * equity / px
                    if qty * px >= params.min_trade_usd:
                        holdings[inst] -= qty
                        notional = qty * px
                        f = notional * fee
                        cash += notional - f
                        trades.append(Trade(t, inst, "sell", qty, px, notional, f, "rebalance"))
                        turnover_notional += notional
            for inst, tgt_w in target.items():
                s = series[inst]
                i = s.at(t)
                if i is None:
                    continue
                px = s.open[i]
                cur_qty = holdings.get(inst, 0.0)
                cur_w = cur_qty * px / equity if equity > 0 else 0.0
                is_new = cur_qty == 0.0
                if not is_new and (tgt_w - cur_w) / tgt_w <= params.rebalance_band:
                    continue
                delta_w = tgt_w - cur_w
                if delta_w <= 0:
                    continue
                notional = min(delta_w * equity, cash / (1 + fee))
                if notional < params.min_trade_usd:
                    continue
                f = notional * fee
                qty = notional / px
                cash -= notional + f
                holdings[inst] = cur_qty + qty
                trades.append(Trade(t, inst, "buy", qty, px, notional, f, "enter" if is_new else "rebalance"))
                turnover_notional += notional
                if is_new:
                    entries += 1
            rebalances += 1
            weekly_weights.append({"ts": t, "regime_on": on, "weights": {k: round(v, 4) for k, v in target.items()}})

            # ---- benchmarks ----
            if with_benchmarks:
                bi = btc.at(t)
                if bh_qty is None and bi is not None:
                    bh_qty = starting_cash * (1 - fee) / btc.open[bi]
                # equal-weight universe, weekly, same costs & band
                ew_equity = _portfolio_value(ew_cash, ew_holdings, series, decision_t, ew_last_px)
                ew_target = {inst: 1.0 / len(universe) for inst in universe} if universe else {}
                for inst in list(ew_holdings):
                    s = series[inst]
                    i = s.at(t)
                    if i is None:
                        continue
                    px = s.open[i]
                    cur_w = ew_holdings[inst] * px / ew_equity if ew_equity > 0 else 0.0
                    tgt_w = ew_target.get(inst, 0.0)
                    if tgt_w == 0.0 or (cur_w > tgt_w and (cur_w - tgt_w) / tgt_w > params.rebalance_band):
                        sell_w = cur_w if tgt_w == 0.0 else cur_w - tgt_w
                        qty = min(ew_holdings[inst], sell_w * ew_equity / px)
                        ew_holdings[inst] -= qty
                        if ew_holdings[inst] <= 1e-12:
                            ew_holdings.pop(inst)
                        ew_cash += qty * px * (1 - fee)
                for inst, tgt_w in ew_target.items():
                    s = series[inst]
                    i = s.at(t)
                    if i is None:
                        continue
                    px = s.open[i]
                    cur_w = ew_holdings.get(inst, 0.0) * px / ew_equity if ew_equity > 0 else 0.0
                    if cur_w > 0 and (tgt_w - cur_w) / tgt_w <= params.rebalance_band:
                        continue
                    notional = min(max(tgt_w - cur_w, 0.0) * ew_equity, ew_cash / (1 + fee))
                    if notional < params.min_trade_usd:
                        continue
                    ew_cash -= notional * (1 + fee)
                    ew_holdings[inst] = ew_holdings.get(inst, 0.0) + notional / px
            first_decision_done = True

        if not first_decision_done:
            continue
        curve_ts.append(t)
        curve.append(_portfolio_value(cash, holdings, series, t, last_px))
        if with_benchmarks:
            bi = btc.at(t)
            bh_curve.append(bh_qty * btc.close[bi] if (bh_qty is not None and bi is not None) else (bh_curve[-1] if bh_curve else starting_cash))
            ew_curve.append(_portfolio_value(ew_cash, ew_holdings, series, t, ew_last_px))

    perf = _perf(curve_ts, curve)
    years = (curve_ts[-1] - curve_ts[0]) / (365.25 * DAY_MS) if len(curve_ts) > 1 else 0.0
    result: dict[str, Any] = {
        "strategy": "xs_momentum",
        "params": asdict(params),
        "cost": asdict(cost),
        "from": curve_ts[0] if curve_ts else None,
        "to": curve_ts[-1] if curve_ts else None,
        "years": years,
        "starting_equity_usd": starting_cash,
        "final_equity_usd": curve[-1] if curve else starting_cash,
        "rebalances": rebalances,
        "entries": entries,
        "trade_count": len(trades),
        "fees_usd": sum(tr.fee for tr in trades),
        # traded notional relative to *average* equity, so a book that grows 7x is not reported as 7x busier
        "turnover_annual_pct": (turnover_notional / (statistics.fmean(curve) if curve else starting_cash) / years * 100.0) if years > 0 else 0.0,
        "regime_off_pct": (sum(1 for _, on in regime_log if not on) / len(regime_log) * 100.0) if regime_log else 0.0,
        **{k: v for k, v in perf.items() if k != "daily_returns"},
        "equity_curve": [{"ts": ts, "equity": round(v, 2)} for ts, v in zip(curve_ts, curve)],
        "weekly": weekly_weights,
        "_daily_returns": perf.get("daily_returns", []),
    }
    if with_benchmarks and bh_curve:
        bh = _perf(curve_ts, bh_curve)
        ew = _perf(curve_ts, ew_curve)
        result["benchmark_btc_hold"] = {k: v for k, v in bh.items() if k != "daily_returns"}
        result["benchmark_equal_weight"] = {k: v for k, v in ew.items() if k != "daily_returns"}
        for p, b, e in zip(result["equity_curve"], bh_curve, ew_curve):
            p["btc_hold"] = round(b, 2)
            p["equal_weight"] = round(e, 2)
    return result


# --------------------------------------------------------------------------- #
# Multiple-testing correction
# --------------------------------------------------------------------------- #


def deflated_sharpe_ratio(
    daily_returns: Sequence[float],
    *,
    n_trials: int,
    sharpe_variance_across_trials: float,
) -> float | None:
    """Bailey & López de Prado (2014). Sharpe here is per-period (daily), not annualised."""
    n = len(daily_returns)
    if n < 30 or n_trials < 1:
        return None
    mean = statistics.fmean(daily_returns)
    sd = statistics.pstdev(daily_returns)
    if sd <= 0:
        return None
    sr = mean / sd
    m3 = sum((r - mean) ** 3 for r in daily_returns) / n / sd**3
    m4 = sum((r - mean) ** 4 for r in daily_returns) / n / sd**4
    nd = statistics.NormalDist()
    if n_trials == 1:
        sr0 = 0.0
    else:
        v = math.sqrt(max(sharpe_variance_across_trials, 0.0))
        sr0 = v * ((1 - EULER_GAMMA) * nd.inv_cdf(1 - 1 / n_trials) + EULER_GAMMA * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    denom = math.sqrt(max(1 - m3 * sr + (m4 - 1) / 4 * sr**2, 1e-12))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return nd.cdf(z)
