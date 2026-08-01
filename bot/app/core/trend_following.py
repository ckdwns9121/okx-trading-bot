"""Daily time-series momentum (trend following) on liquid majors.

Signal: an ensemble of simple moving averages (default 20/50/100 day).
The target exposure for an instrument is the fraction of MAs the last
confirmed daily close sits above — long/flat only, no shorts. The evidence
for this family of strategies is strongest exactly in this configuration:
daily bars, BTC/ETH, trend-with (not counter-trend), parameter ensemble.

This module is pure logic: signals, rebalance planning, a paper book, and
a cost-aware backtest. The paper trader script feeds it live OKX data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_MA_PERIODS: tuple[int, ...] = (20, 50, 100)


# --------------------------------------------------------------------------- #
# Signal
# --------------------------------------------------------------------------- #


def compute_sma(closes: Sequence[float], period: int) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


@dataclass(frozen=True)
class TrendSignal:
    inst_id: str
    close: float
    ma_values: dict[int, float | None]
    votes: int
    total: int

    @property
    def target_fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.votes / self.total

    @property
    def ready(self) -> bool:
        """True when every MA in the ensemble has enough history."""
        return all(value is not None for value in self.ma_values.values())


def evaluate_trend(
    inst_id: str,
    closes: Sequence[float],
    *,
    ma_periods: Sequence[int] = DEFAULT_MA_PERIODS,
) -> TrendSignal:
    if not closes:
        raise ValueError("closes cannot be empty")
    if not ma_periods:
        raise ValueError("ma_periods cannot be empty")

    close = float(closes[-1])
    ma_values: dict[int, float | None] = {}
    votes = 0
    for period in ma_periods:
        ma = compute_sma(closes, period)
        ma_values[int(period)] = ma
        if ma is not None and close > ma:
            votes += 1
    return TrendSignal(
        inst_id=inst_id,
        close=close,
        ma_values=ma_values,
        votes=votes,
        total=len(ma_periods),
    )


# --------------------------------------------------------------------------- #
# Rebalance planning (long/flat only)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RebalanceOrder:
    inst_id: str
    side: str  # "buy" | "sell"
    quantity: float
    notional_usd: float
    target_fraction: float


def plan_rebalance(
    *,
    inst_id: str,
    target_fraction: float,
    allocation_usd: float,
    current_quantity: float,
    price: float,
    min_trade_usd: float = 25.0,
) -> RebalanceOrder | None:
    """Compute the order that moves the position to the target exposure."""

    if not 0.0 <= target_fraction <= 1.0:
        raise ValueError("target_fraction must be within [0, 1]")
    if allocation_usd <= 0.0:
        raise ValueError("allocation_usd must be positive")
    if price <= 0.0:
        raise ValueError("price must be positive")
    if current_quantity < 0.0:
        raise ValueError("long/flat book cannot hold negative quantity")

    target_notional = target_fraction * allocation_usd
    current_notional = current_quantity * price
    delta = target_notional - current_notional
    if abs(delta) < min_trade_usd:
        return None

    if delta > 0:
        quantity = delta / price
        side = "buy"
        notional = delta
    else:
        quantity = min(abs(delta) / price, current_quantity)
        if quantity <= 0.0:
            return None
        side = "sell"
        notional = quantity * price

    return RebalanceOrder(
        inst_id=inst_id,
        side=side,
        quantity=quantity,
        notional_usd=notional,
        target_fraction=target_fraction,
    )


# --------------------------------------------------------------------------- #
# Paper book
# --------------------------------------------------------------------------- #


@dataclass
class PaperPosition:
    quantity: float = 0.0
    avg_entry_price: float = 0.0


@dataclass
class PaperBook:
    cash_usd: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    realized_pnl_usd: float = 0.0
    fees_paid_usd: float = 0.0

    def position(self, inst_id: str) -> PaperPosition:
        return self.positions.setdefault(inst_id, PaperPosition())

    def equity_usd(self, prices: Mapping[str, float]) -> float:
        holdings = 0.0
        for inst_id, position in self.positions.items():
            price = float(prices.get(inst_id, 0.0))
            holdings += position.quantity * price
        return self.cash_usd + holdings

    def to_payload(self) -> dict[str, Any]:
        return {
            "cash_usd": self.cash_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "fees_paid_usd": self.fees_paid_usd,
            "positions": {
                inst_id: {
                    "quantity": position.quantity,
                    "avg_entry_price": position.avg_entry_price,
                }
                for inst_id, position in self.positions.items()
                if position.quantity > 0.0
            },
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PaperBook":
        book = cls(
            cash_usd=float(payload.get("cash_usd") or 0.0),
            realized_pnl_usd=float(payload.get("realized_pnl_usd") or 0.0),
            fees_paid_usd=float(payload.get("fees_paid_usd") or 0.0),
        )
        for inst_id, row in (payload.get("positions") or {}).items():
            book.positions[str(inst_id)] = PaperPosition(
                quantity=float(row.get("quantity") or 0.0),
                avg_entry_price=float(row.get("avg_entry_price") or 0.0),
            )
        return book


def affordable_quantity(cash_usd: float, price: float, fee_pct: float) -> float:
    """Largest quantity a buy can take without overdrawing cash (fee included)."""
    if price <= 0.0:
        raise ValueError("price must be positive")
    if cash_usd <= 0.0:
        return 0.0
    return cash_usd / (price * (1.0 + fee_pct / 100.0))


def apply_paper_fill(
    book: PaperBook,
    *,
    inst_id: str,
    side: str,
    quantity: float,
    price: float,
    fee_pct: float,
) -> dict[str, Any]:
    """Apply a simulated fill to the paper book. Returns the trade record."""

    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if quantity <= 0.0 or price <= 0.0:
        raise ValueError("quantity and price must be positive")
    if fee_pct < 0.0:
        raise ValueError("fee_pct cannot be negative")

    position = book.position(inst_id)
    notional = quantity * price
    fee = notional * fee_pct / 100.0
    realized: float | None = None

    if side == "buy":
        if book.cash_usd + 1e-6 < notional + fee:
            raise ValueError(
                f"insufficient paper cash ${book.cash_usd:,.2f} for ${notional + fee:,.2f}"
            )
        total_cost = position.avg_entry_price * position.quantity + notional
        position.quantity += quantity
        position.avg_entry_price = total_cost / position.quantity
        book.cash_usd = max(book.cash_usd - (notional + fee), 0.0)
    else:
        if quantity > position.quantity + 1e-12:
            raise ValueError("cannot sell more than the paper position holds")
        realized = (price - position.avg_entry_price) * quantity - fee
        position.quantity = max(position.quantity - quantity, 0.0)
        if position.quantity == 0.0:
            position.avg_entry_price = 0.0
        book.cash_usd += notional - fee
        book.realized_pnl_usd += realized

    book.fees_paid_usd += fee
    return {
        "inst_id": inst_id,
        "side": side,
        "quantity": quantity,
        "price": price,
        "notional_usd": notional,
        "fee_usd": fee,
        "realized_pnl_usd": realized,
    }


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #


def _max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    peak = float("-inf")
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100.0)
    return max_dd


def backtest_trend_following(
    candles_by_inst: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    ma_periods: Sequence[int] = DEFAULT_MA_PERIODS,
    allocation_usd_per_inst: float = 1000.0,
    fee_pct_per_side: float = 0.10,
    min_trade_usd: float = 25.0,
) -> dict[str, Any]:
    """Cost-aware daily backtest, decision at close t, fill at open t+1.

    ``candles_by_inst`` maps inst_id to ascending daily candles with
    ``open``/``close`` keys. Signals never see the fill candle, so there is
    no look-ahead. Returns portfolio stats plus a buy-and-hold benchmark.
    """

    if not candles_by_inst:
        raise ValueError("candles_by_inst cannot be empty")
    warmup = max(ma_periods)

    book = PaperBook(cash_usd=allocation_usd_per_inst * len(candles_by_inst))
    trade_count = 0
    equity_curve: list[float] = []

    per_inst_closes = {
        inst_id: [float(row["close"]) for row in rows]
        for inst_id, rows in candles_by_inst.items()
    }
    length = min(len(rows) for rows in candles_by_inst.values())
    if length <= warmup + 1:
        raise ValueError(
            f"need more than {warmup + 1} candles per instrument, got {length}"
        )

    for index in range(warmup, length - 1):
        for inst_id, rows in candles_by_inst.items():
            closes = per_inst_closes[inst_id][: index + 1]
            signal = evaluate_trend(inst_id, closes, ma_periods=ma_periods)
            if not signal.ready:
                continue
            fill_price = float(rows[index + 1]["open"])
            order = plan_rebalance(
                inst_id=inst_id,
                target_fraction=signal.target_fraction,
                allocation_usd=allocation_usd_per_inst,
                current_quantity=book.position(inst_id).quantity,
                price=fill_price,
                min_trade_usd=min_trade_usd,
            )
            if order is None:
                continue
            quantity = order.quantity
            if order.side == "buy":
                quantity = min(
                    quantity,
                    affordable_quantity(book.cash_usd, fill_price, fee_pct_per_side),
                )
                if quantity * fill_price < min_trade_usd:
                    continue
            apply_paper_fill(
                book,
                inst_id=inst_id,
                side=order.side,
                quantity=quantity,
                price=fill_price,
                fee_pct=fee_pct_per_side,
            )
            trade_count += 1

        marks = {
            inst_id: float(rows[index + 1]["close"])
            for inst_id, rows in candles_by_inst.items()
        }
        equity_curve.append(book.equity_usd(marks))

    starting_equity = allocation_usd_per_inst * len(candles_by_inst)
    final_equity = equity_curve[-1] if equity_curve else starting_equity

    # Buy-and-hold benchmark: buy at the first fill opportunity, hold to the end.
    bh_curve: list[float] = []
    bh_quantities = {}
    for inst_id, rows in candles_by_inst.items():
        entry_price = float(rows[warmup + 1]["open"])
        fee = allocation_usd_per_inst * fee_pct_per_side / 100.0
        bh_quantities[inst_id] = (allocation_usd_per_inst - fee) / entry_price
    for index in range(warmup, length - 1):
        value = sum(
            bh_quantities[inst_id] * float(rows[index + 1]["close"])
            for inst_id, rows in candles_by_inst.items()
        )
        bh_curve.append(value)

    return {
        "instruments": sorted(candles_by_inst),
        "days_tested": length - warmup - 1,
        "ma_periods": [int(period) for period in ma_periods],
        "starting_equity_usd": starting_equity,
        "final_equity_usd": final_equity,
        "total_return_pct": ((final_equity / starting_equity) - 1.0) * 100.0,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "trade_count": trade_count,
        "fees_paid_usd": book.fees_paid_usd,
        "buy_hold_return_pct": (
            ((bh_curve[-1] / starting_equity) - 1.0) * 100.0 if bh_curve else 0.0
        ),
        "buy_hold_max_drawdown_pct": _max_drawdown_pct(bh_curve),
    }
