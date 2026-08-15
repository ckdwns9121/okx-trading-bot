"""Donchian channel breakout (Turtle-style) on daily bars, long/flat.

Rules (System 1 defaults: 20-day entry / 10-day exit):
- Enter long when the confirmed close breaks above the prior N-day high.
- Exit when the close breaks below the prior M-day low, or when the close
  falls more than ``atr_stop_mult`` × ATR(atr_period) below the entry price.

Decisions use only bars up to and including t; fills happen at open t+1,
so there is no look-ahead. Pure logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core.indicators import atr_wilder
from app.core.trend_following import (
    PaperBook,
    _max_drawdown_pct,
    affordable_quantity,
    apply_paper_fill,
)


@dataclass(frozen=True)
class DonchianParams:
    entry_period: int = 20
    exit_period: int = 10
    atr_period: int = 20
    atr_stop_mult: float | None = 2.0

    def warmup(self) -> int:
        return max(self.entry_period, self.exit_period, self.atr_period) + 1


@dataclass(frozen=True)
class DonchianDecision:
    action: str  # "enter" | "exit" | "hold"
    reason: str
    prior_high: float | None
    prior_low: float | None


def decide(
    *,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    in_position: bool,
    entry_price: float | None,
    atr_at_entry: float | None,
    params: DonchianParams,
) -> DonchianDecision:
    """Decision for the latest confirmed bar (index -1 of the inputs)."""

    if len(closes) < params.warmup():
        return DonchianDecision("hold", "warmup", None, None)

    close = closes[-1]
    # Channels exclude the current bar: break of the *prior* N-day extreme.
    prior_high = max(highs[-params.entry_period - 1 : -1])
    prior_low = min(lows[-params.exit_period - 1 : -1])

    if not in_position:
        if close > prior_high:
            return DonchianDecision("enter", "breakout_above_entry_channel", prior_high, prior_low)
        return DonchianDecision("hold", "no_breakout", prior_high, prior_low)

    if close < prior_low:
        return DonchianDecision("exit", "breakdown_below_exit_channel", prior_high, prior_low)
    if (
        params.atr_stop_mult is not None
        and entry_price is not None
        and atr_at_entry is not None
        and close < entry_price - params.atr_stop_mult * atr_at_entry
    ):
        return DonchianDecision("exit", "atr_stop", prior_high, prior_low)
    return DonchianDecision("hold", "in_trend", prior_high, prior_low)


def backtest_donchian(
    candles_by_inst: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    params: DonchianParams = DonchianParams(),
    allocation_usd_per_inst: float = 1000.0,
    fee_pct_per_side: float = 0.10,
    min_trade_usd: float = 25.0,
) -> dict[str, Any]:
    """Cost-aware daily backtest: decision at close t, fill at open t+1."""

    if not candles_by_inst:
        raise ValueError("candles_by_inst cannot be empty")
    warmup = params.warmup()
    length = min(len(rows) for rows in candles_by_inst.values())
    if length <= warmup + 1:
        raise ValueError(f"need more than {warmup + 1} candles, got {length}")

    series = {
        inst_id: {
            "highs": [float(row["high"]) for row in rows],
            "lows": [float(row["low"]) for row in rows],
            "closes": [float(row["close"]) for row in rows],
        }
        for inst_id, rows in candles_by_inst.items()
    }
    atr_by_inst = {
        inst_id: atr_wilder(data["highs"], data["lows"], data["closes"], params.atr_period)
        for inst_id, data in series.items()
    }

    book = PaperBook(cash_usd=allocation_usd_per_inst * len(candles_by_inst))
    entry_info: dict[str, dict[str, float]] = {}
    trade_count = 0
    wins = 0
    equity_curve: list[float] = []

    for index in range(warmup, length - 1):
        for inst_id, rows in candles_by_inst.items():
            data = series[inst_id]
            position = book.position(inst_id)
            info = entry_info.get(inst_id)
            decision = decide(
                highs=data["highs"][: index + 1],
                lows=data["lows"][: index + 1],
                closes=data["closes"][: index + 1],
                in_position=position.quantity > 0.0,
                entry_price=info["entry_price"] if info else None,
                atr_at_entry=info["atr"] if info else None,
                params=params,
            )
            if decision.action == "hold":
                continue
            fill_price = float(rows[index + 1]["open"])

            if decision.action == "enter":
                quantity = min(
                    allocation_usd_per_inst / fill_price,
                    affordable_quantity(book.cash_usd, fill_price, fee_pct_per_side),
                )
                if quantity * fill_price < min_trade_usd:
                    continue
                apply_paper_fill(
                    book,
                    inst_id=inst_id,
                    side="buy",
                    quantity=quantity,
                    price=fill_price,
                    fee_pct=fee_pct_per_side,
                )
                atr_value = atr_by_inst[inst_id][index]
                entry_info[inst_id] = {
                    "entry_price": fill_price,
                    "atr": float(atr_value) if atr_value is not None else 0.0,
                }
                trade_count += 1
            else:
                quantity = position.quantity
                if quantity <= 0.0:
                    continue
                record = apply_paper_fill(
                    book,
                    inst_id=inst_id,
                    side="sell",
                    quantity=quantity,
                    price=fill_price,
                    fee_pct=fee_pct_per_side,
                )
                if (record["realized_pnl_usd"] or 0.0) > 0.0:
                    wins += 1
                entry_info.pop(inst_id, None)
                trade_count += 1

        marks = {
            inst_id: float(rows[index + 1]["close"])
            for inst_id, rows in candles_by_inst.items()
        }
        equity_curve.append(book.equity_usd(marks))

    starting_equity = allocation_usd_per_inst * len(candles_by_inst)
    final_equity = equity_curve[-1] if equity_curve else starting_equity
    round_trips = trade_count // 2
    return {
        "strategy": "donchian_breakout",
        "params": {
            "entry_period": params.entry_period,
            "exit_period": params.exit_period,
            "atr_stop_mult": params.atr_stop_mult,
        },
        "instruments": sorted(candles_by_inst),
        "days_tested": length - warmup - 1,
        "starting_equity_usd": starting_equity,
        "final_equity_usd": final_equity,
        "total_return_pct": ((final_equity / starting_equity) - 1.0) * 100.0,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "trade_count": trade_count,
        "win_rate_pct": (wins / round_trips * 100.0) if round_trips else 0.0,
        "fees_paid_usd": book.fees_paid_usd,
    }
