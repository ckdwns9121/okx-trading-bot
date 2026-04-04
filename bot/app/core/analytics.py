"""Trade analytics and Monte Carlo simulation for strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Union

import numpy as np

from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Type alias for a trade record (dict or object with pnl/entry_time/exit_time)
# ---------------------------------------------------------------------------
Trade = Union[dict[str, Any], Any]


def _get(trade: Trade, key: str) -> Any:
    """Retrieve a field from a trade dict or object."""
    if isinstance(trade, dict):
        return trade[key]
    return getattr(trade, key)


# ---------------------------------------------------------------------------
# Part 1: TradeAnalytics
# ---------------------------------------------------------------------------


@dataclass
class TradeAnalytics:
    profit_factor: float          # sum(wins) / abs(sum(losses)), inf if no losses
    avg_win: float                # average PnL of winning trades
    avg_loss: float               # average PnL of losing trades (negative number)
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_hold_time_minutes: float
    best_trade_pnl: float
    worst_trade_pnl: float
    expectancy: float             # avg_win * win_rate - abs(avg_loss) * loss_rate
    payoff_ratio: float           # abs(avg_win / avg_loss)
    total_trades: int
    winning_trades: int
    losing_trades: int


def _max_consecutive(flags: list[bool], value: bool) -> int:
    """Return the longest run of `value` in `flags`."""
    max_run = current = 0
    for f in flags:
        if f == value:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def compute_trade_analytics(
    trades: list[Trade],
    initial_balance: float,  # noqa: ARG001 – reserved for future normalised metrics
) -> TradeAnalytics:
    """Compute detailed trade analytics from a list of closed trades.

    Parameters
    ----------
    trades:
        List of trade dicts or objects.  Each must expose ``pnl`` (float),
        ``entry_time`` (datetime), and ``exit_time`` (datetime).
    initial_balance:
        Starting capital.  Accepted for API symmetry with
        :func:`monte_carlo_simulation`; reserved for future use.

    Returns
    -------
    TradeAnalytics
        Populated analytics dataclass.  Safe to call with an empty list.
    """
    total_trades = len(trades)

    if total_trades == 0:
        logger.info("compute_trade_analytics called with zero trades")
        return TradeAnalytics(
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            avg_hold_time_minutes=0.0,
            best_trade_pnl=0.0,
            worst_trade_pnl=0.0,
            expectancy=0.0,
            payoff_ratio=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
        )

    pnls: list[float] = [float(_get(t, "pnl")) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    winning_trades = len(wins)
    losing_trades = len(losses)

    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0  # negative

    sum_wins = sum(wins)
    sum_losses = sum(losses)

    if sum_losses == 0:
        profit_factor = float("inf")
    else:
        profit_factor = sum_wins / abs(sum_losses)

    win_rate = winning_trades / total_trades
    loss_rate = losing_trades / total_trades

    expectancy = avg_win * win_rate - abs(avg_loss) * loss_rate

    if avg_loss == 0:
        payoff_ratio = float("inf")
    else:
        payoff_ratio = abs(avg_win / avg_loss)

    is_win: list[bool] = [p > 0 for p in pnls]
    max_consecutive_wins = _max_consecutive(is_win, True)
    max_consecutive_losses = _max_consecutive(is_win, False)

    hold_minutes: list[float] = []
    for t in trades:
        entry: datetime = _get(t, "entry_time")
        exit_: datetime = _get(t, "exit_time")
        hold_minutes.append((exit_ - entry).total_seconds() / 60.0)

    avg_hold_time_minutes = float(np.mean(hold_minutes)) if hold_minutes else 0.0
    best_trade_pnl = max(pnls)
    worst_trade_pnl = min(pnls)

    logger.debug(
        "trade analytics computed",
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        profit_factor=profit_factor,
        expectancy=expectancy,
    )

    return TradeAnalytics(
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
        avg_hold_time_minutes=avg_hold_time_minutes,
        best_trade_pnl=best_trade_pnl,
        worst_trade_pnl=worst_trade_pnl,
        expectancy=expectancy,
        payoff_ratio=payoff_ratio,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
    )


# ---------------------------------------------------------------------------
# Part 2: MonteCarloResult
# ---------------------------------------------------------------------------


@dataclass
class MonteCarloResult:
    median_final_balance: float
    p5_final_balance: float      # 5th percentile (worst case)
    p95_final_balance: float     # 95th percentile (best case)
    median_max_drawdown: float   # as positive fraction e.g. 0.15 = 15%
    p95_max_drawdown: float      # worst 95th-percentile drawdown
    ruin_probability: float      # fraction of sims ending below 50% of initial
    n_simulations: int


def monte_carlo_simulation(
    trades: list[Trade],
    initial_balance: float,
    n_simulations: int = 1000,
) -> MonteCarloResult:
    """Run Monte Carlo simulation by shuffling trade PnL sequences.

    For each simulation the trade returns are randomly reordered and replayed
    against ``initial_balance`` to produce an equity curve.  Aggregate
    statistics (percentiles of final balance and max drawdown) are returned.

    Parameters
    ----------
    trades:
        Closed trade records.  Each must expose a ``pnl`` (float) field.
    initial_balance:
        Starting capital for every simulation path.
    n_simulations:
        Number of Monte Carlo paths to generate.

    Returns
    -------
    MonteCarloResult
        Percentile statistics across all simulated paths.
    """
    pnls = np.array([float(_get(t, "pnl")) for t in trades], dtype=np.float64)
    n_trades = len(pnls)

    if n_trades == 0:
        logger.info("monte_carlo_simulation called with zero trades")
        return MonteCarloResult(
            median_final_balance=initial_balance,
            p5_final_balance=initial_balance,
            p95_final_balance=initial_balance,
            median_max_drawdown=0.0,
            p95_max_drawdown=0.0,
            ruin_probability=0.0,
            n_simulations=n_simulations,
        )

    logger.info(
        "starting monte carlo simulation",
        n_simulations=n_simulations,
        n_trades=n_trades,
        initial_balance=initial_balance,
    )

    # Build shuffled index matrix: shape (n_simulations, n_trades)
    rng = np.random.default_rng()
    indices = np.argsort(
        rng.random((n_simulations, n_trades)), axis=1
    )  # each row is a random permutation
    shuffled_pnls = pnls[indices]  # (n_simulations, n_trades)

    # Equity curves: prepend initial_balance column, then cumsum the PnL columns
    cumulative_pnl = np.cumsum(shuffled_pnls, axis=1)  # (n_simulations, n_trades)
    # equity shape: (n_simulations, n_trades + 1) with initial balance prepended
    equity = np.empty((n_simulations, n_trades + 1), dtype=np.float64)
    equity[:, 0] = initial_balance
    equity[:, 1:] = initial_balance + cumulative_pnl

    final_balances = equity[:, -1]  # (n_simulations,)

    # Vectorised max-drawdown per simulation
    peak = np.maximum.accumulate(equity, axis=1)  # (n_simulations, n_trades+1)
    safe_peak = np.where(peak == 0, 1.0, peak)
    drawdowns = (peak - equity) / safe_peak          # (n_simulations, n_trades+1)
    max_drawdowns = np.max(drawdowns, axis=1)         # (n_simulations,)

    ruin_threshold = initial_balance * 0.5
    ruin_probability = float(np.mean(final_balances < ruin_threshold))

    result = MonteCarloResult(
        median_final_balance=float(np.percentile(final_balances, 50)),
        p5_final_balance=float(np.percentile(final_balances, 5)),
        p95_final_balance=float(np.percentile(final_balances, 95)),
        median_max_drawdown=float(np.percentile(max_drawdowns, 50)),
        p95_max_drawdown=float(np.percentile(max_drawdowns, 95)),
        ruin_probability=ruin_probability,
        n_simulations=n_simulations,
    )

    logger.info(
        "monte carlo simulation complete",
        median_final_balance=result.median_final_balance,
        p5_final_balance=result.p5_final_balance,
        p95_final_balance=result.p95_final_balance,
        median_max_drawdown=result.median_max_drawdown,
        p95_max_drawdown=result.p95_max_drawdown,
        ruin_probability=result.ruin_probability,
    )

    return result
