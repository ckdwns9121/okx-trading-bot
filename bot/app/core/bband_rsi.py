"""Bollinger + RSI mean reversion on 1h bars (freqtrade BbandRsi port).

Rules from the freqtrade org repo (berlinguyinca/BbandRsi.py):
- Entry: RSI(14) < 30 AND close < lower Bollinger Band (20, 2σ)
- Exit: RSI(14) > 70, or take-profit at +10%, or stoploss at −25%

Long-only. Decisions on confirmed bar t, fills at open t+1 — no look-ahead.
The stop/ROI checks use bar closes (matching hourly polling reality) rather
than intrabar touches. Pure logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core.indicators import bollinger_bands, rsi_wilder
from app.core.trend_following import (
    PaperBook,
    _max_drawdown_pct,
    affordable_quantity,
    apply_paper_fill,
)


@dataclass(frozen=True)
class BbandRsiParams:
    rsi_period: int = 14
    entry_rsi: float = 30.0
    exit_rsi: float = 70.0
    bb_period: int = 20
    bb_stddev: float = 2.0
    take_profit_pct: float = 10.0
    stoploss_pct: float = 25.0

    def warmup(self) -> int:
        return max(self.rsi_period, self.bb_period) + 1


def backtest_bband_rsi(
    hourly_by_inst: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    params: BbandRsiParams = BbandRsiParams(),
    allocation_usd_per_inst: float = 1000.0,
    fee_pct_per_side: float = 0.10,
    min_trade_usd: float = 25.0,
) -> dict[str, Any]:
    if not hourly_by_inst:
        raise ValueError("hourly_by_inst cannot be empty")
    warmup = params.warmup()
    length = min(len(rows) for rows in hourly_by_inst.values())
    if length <= warmup + 1:
        raise ValueError(f"need more than {warmup + 1} candles, got {length}")

    series: dict[str, dict[str, Any]] = {}
    for inst_id, rows in hourly_by_inst.items():
        closes = [float(row["close"]) for row in rows]
        _, _, lower = bollinger_bands(closes, params.bb_period, params.bb_stddev)
        series[inst_id] = {
            "closes": closes,
            "rsi": rsi_wilder(closes, params.rsi_period),
            "bb_lower": lower,
        }

    book = PaperBook(cash_usd=allocation_usd_per_inst * len(hourly_by_inst))
    entry_price: dict[str, float] = {}
    trade_count = 0
    wins = 0
    equity_curve: list[float] = []

    for index in range(warmup, length - 1):
        for inst_id, rows in hourly_by_inst.items():
            data = series[inst_id]
            rsi = data["rsi"][index]
            lower = data["bb_lower"][index]
            close = data["closes"][index]
            if rsi is None or lower is None:
                continue
            position = book.position(inst_id)
            fill_price = float(rows[index + 1]["open"])

            if position.quantity <= 0.0:
                if rsi < params.entry_rsi and close < lower:
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
                    entry_price[inst_id] = fill_price
                    trade_count += 1
                continue

            entered_at = entry_price.get(inst_id, position.avg_entry_price)
            change_pct = (close / entered_at - 1.0) * 100.0
            should_exit = (
                rsi > params.exit_rsi
                or change_pct >= params.take_profit_pct
                or change_pct <= -params.stoploss_pct
            )
            if not should_exit:
                continue
            record = apply_paper_fill(
                book,
                inst_id=inst_id,
                side="sell",
                quantity=position.quantity,
                price=fill_price,
                fee_pct=fee_pct_per_side,
            )
            if (record["realized_pnl_usd"] or 0.0) > 0.0:
                wins += 1
            entry_price.pop(inst_id, None)
            trade_count += 1

        marks = {
            inst_id: float(rows[index + 1]["close"])
            for inst_id, rows in hourly_by_inst.items()
        }
        equity_curve.append(book.equity_usd(marks))

    starting_equity = allocation_usd_per_inst * len(hourly_by_inst)
    final_equity = equity_curve[-1] if equity_curve else starting_equity
    round_trips = trade_count // 2
    return {
        "strategy": "bband_rsi",
        "params": {
            "rsi_period": params.rsi_period,
            "entry_rsi": params.entry_rsi,
            "exit_rsi": params.exit_rsi,
            "bb_period": params.bb_period,
            "take_profit_pct": params.take_profit_pct,
            "stoploss_pct": params.stoploss_pct,
        },
        "instruments": sorted(hourly_by_inst),
        "days_tested": (length - warmup - 1) // 24,
        "starting_equity_usd": starting_equity,
        "final_equity_usd": final_equity,
        "total_return_pct": ((final_equity / starting_equity) - 1.0) * 100.0,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "trade_count": trade_count,
        "win_rate_pct": (wins / round_trips * 100.0) if round_trips else 0.0,
        "fees_paid_usd": book.fees_paid_usd,
    }
