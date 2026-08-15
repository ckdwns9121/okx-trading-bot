"""Larry Williams volatility breakout on daily ranges, executed on 1h bars.

Canonical crypto form (Korean quant-retail standard):
- target = today's open + k × (yesterday's high − yesterday's low), k = 0.5
- optional trend filter: only trade days whose open > SMA(ma_period) of
  prior daily closes
- exit at the next day's open (holding period = to next daily open)

This implementation is deliberately honest about hourly polling: the entry
triggers on the first *confirmed hourly close* at/above the target and fills
at the next hourly open — never at the theoretical breakout price. Days are
grouped by UTC date. Pure logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.core.trend_following import (
    PaperBook,
    _max_drawdown_pct,
    affordable_quantity,
    apply_paper_fill,
)


@dataclass(frozen=True)
class VolatilityBreakoutParams:
    k: float = 0.5
    ma_period: int = 5
    use_ma_filter: bool = True


@dataclass
class DayBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    first_index: int  # index of the day's first hourly candle


def group_hourly_into_days(candles: Sequence[Mapping[str, Any]]) -> list[DayBar]:
    """Aggregate ascending hourly candles into UTC day bars."""

    days: list[DayBar] = []
    for index, row in enumerate(candles):
        ts_ms = int(row["timestamp"])
        date = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if days and days[-1].date == date:
            day = days[-1]
            day.high = max(day.high, high)
            day.low = min(day.low, low)
            day.close = close
        else:
            days.append(
                DayBar(date=date, open=open_, high=high, low=low, close=close, first_index=index)
            )
    return days


def backtest_volatility_breakout(
    hourly_by_inst: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    params: VolatilityBreakoutParams = VolatilityBreakoutParams(),
    allocation_usd_per_inst: float = 1000.0,
    fee_pct_per_side: float = 0.10,
    min_trade_usd: float = 25.0,
) -> dict[str, Any]:
    """Cost-aware backtest on hourly candles.

    Entry: first hourly close ≥ target → buy at next hourly open (same day).
    Exit: sell at the first hourly open of the next day.
    """

    if not hourly_by_inst:
        raise ValueError("hourly_by_inst cannot be empty")

    book = PaperBook(cash_usd=allocation_usd_per_inst * len(hourly_by_inst))
    trade_count = 0
    wins = 0
    equity_curve: list[float] = []

    prepared: dict[str, dict[str, Any]] = {}
    for inst_id, candles in hourly_by_inst.items():
        days = group_hourly_into_days(candles)
        if len(days) <= params.ma_period + 2:
            raise ValueError(f"{inst_id}: not enough full days for backtest")
        day_index_by_candle: list[int] = []
        cursor = 0
        for index in range(len(candles)):
            if cursor + 1 < len(days) and index >= days[cursor + 1].first_index:
                cursor += 1
            day_index_by_candle.append(cursor)
        prepared[inst_id] = {
            "candles": candles,
            "days": days,
            "day_of": day_index_by_candle,
        }

    length = min(len(item["candles"]) for item in prepared.values())
    in_position: dict[str, bool] = {inst_id: False for inst_id in prepared}

    for index in range(length - 1):
        for inst_id, data in prepared.items():
            candles = data["candles"]
            days: list[DayBar] = data["days"]
            day_idx = data["day_of"][index]
            next_day_idx = data["day_of"][index + 1]
            row = candles[index]
            next_open = float(candles[index + 1]["open"])

            # Exit: next candle opens a new day → sell at that open.
            if in_position[inst_id] and next_day_idx != day_idx:
                position = book.position(inst_id)
                if position.quantity > 0.0:
                    record = apply_paper_fill(
                        book,
                        inst_id=inst_id,
                        side="sell",
                        quantity=position.quantity,
                        price=next_open,
                        fee_pct=fee_pct_per_side,
                    )
                    if (record["realized_pnl_usd"] or 0.0) > 0.0:
                        wins += 1
                    trade_count += 1
                in_position[inst_id] = False
                continue

            if in_position[inst_id] or day_idx < params.ma_period + 1:
                continue
            if next_day_idx != day_idx:
                continue  # never enter on the day's last candle

            day = days[day_idx]
            prev_day = days[day_idx - 1]
            target = day.open + params.k * (prev_day.high - prev_day.low)
            if params.use_ma_filter:
                closes = [days[i].close for i in range(day_idx - params.ma_period, day_idx)]
                if day.open <= sum(closes) / params.ma_period:
                    continue
            if float(row["close"]) < target:
                continue

            quantity = min(
                allocation_usd_per_inst / next_open,
                affordable_quantity(book.cash_usd, next_open, fee_pct_per_side),
            )
            if quantity * next_open < min_trade_usd:
                continue
            apply_paper_fill(
                book,
                inst_id=inst_id,
                side="buy",
                quantity=quantity,
                price=next_open,
                fee_pct=fee_pct_per_side,
            )
            in_position[inst_id] = True
            trade_count += 1

        marks = {
            inst_id: float(data["candles"][index + 1]["close"])
            for inst_id, data in prepared.items()
        }
        equity_curve.append(book.equity_usd(marks))

    starting_equity = allocation_usd_per_inst * len(hourly_by_inst)
    final_equity = equity_curve[-1] if equity_curve else starting_equity
    round_trips = trade_count // 2
    return {
        "strategy": "volatility_breakout",
        "params": {
            "k": params.k,
            "ma_period": params.ma_period,
            "use_ma_filter": params.use_ma_filter,
        },
        "instruments": sorted(hourly_by_inst),
        "days_tested": min(len(data["days"]) for data in prepared.values()),
        "starting_equity_usd": starting_equity,
        "final_equity_usd": final_equity,
        "total_return_pct": ((final_equity / starting_equity) - 1.0) * 100.0,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "trade_count": trade_count,
        "win_rate_pct": (wins / round_trips * 100.0) if round_trips else 0.0,
        "fees_paid_usd": book.fees_paid_usd,
    }
