"""Bayesian parameter optimization for trading strategies.

Implements a TPE-inspired (Tree-structured Parzen Estimator) approach
for optimizing strategy parameters with walk-forward validation.
No external optimization libraries required — uses numpy + scipy.stats only.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from scipy.stats import norm

from app.core.backtest_engine import BacktestEngine, BacktestResult
from app.core.strategy_base import BaseStrategy
from app.core.strategy_registry import registry
from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TrialResult:
    trial_number: int
    params: dict[str, float]
    train_sharpe: float
    train_pnl: float
    train_win_rate: float
    val_sharpe: float
    val_pnl: float
    val_win_rate: float
    score: float  # the objective value (val metric by default)


@dataclass
class OptimizationResult:
    strategy_name: str
    pair: str
    best_params: dict[str, float]
    best_score: float
    total_trials: int
    trials: list[TrialResult]
    train_period: str
    val_period: str


# ---------------------------------------------------------------------------
# Default parameter spaces per strategy
# ---------------------------------------------------------------------------

DEFAULT_PARAM_SPACES: dict[str, dict[str, tuple[float, float]]] = {
    "example_rsi": {
        "rsi_period": (7, 21),
        "oversold": (20.0, 40.0),
        "overbought": (60.0, 80.0),
    },
    "example_sma_cross": {
        "fast_period": (5, 15),
        "slow_period": (20, 50),
    },
    "bollinger_band": {
        "period": (10, 30),
        "std_dev": (1.5, 3.0),
    },
    "macd_strategy": {
        "fast_period": (8, 16),
        "slow_period": (20, 32),
        "signal_period": (6, 12),
    },
    "breakout_strategy": {
        "channel_period": (10, 30),
    },
    "mean_reversion": {
        "period": (15, 40),
        "entry_z": (1.5, 3.0),
        "exit_z": (0.3, 0.8),
    },
    "rsi_bollinger_combo": {
        "rsi_period": (7, 21),
        "rsi_oversold": (25.0, 40.0),
        "rsi_overbought": (60.0, 75.0),
        "bb_period": (15, 25),
        "bb_std": (1.5, 2.5),
    },
    "volume_momentum": {
        "period": (10, 30),
        "volume_threshold": (1.2, 2.5),
        "momentum_threshold": (1.0, 4.0),
    },
    "multi_ema": {
        "fast": (5, 12),
        "medium": (15, 30),
        "slow": (40, 65),
    },
    "elliott_wave_fib": {
        "swing_threshold": (1.5, 4.0),
        "rsi_period": (10, 20),
        "volume_period": (10, 30),
    },
    "livermore": {
        "pivot_period": (10, 30),
        "volume_factor": (1.1, 2.0),
        "trend_ema_period": (30, 70),
        "max_pyramids": (1, 4),
        "initial_stop_pct": (0.02, 0.05),
        "trail_step_pct": (0.01, 0.03),
    },
    "multi_factor": {
        "momentum_period": (7, 21),
        "adx_period": (10, 20),
        "rsi_period": (7, 21),
        "volume_period": (10, 30),
        "bb_period": (15, 25),
        "w_momentum": (0.1, 0.4),
        "w_trend": (0.1, 0.4),
        "w_rsi": (0.05, 0.3),
        "entry_threshold": (0.2, 0.5),
        "exit_threshold": (0.05, 0.2),
    },
}


def _is_integer_param(name: str, low: float, high: float) -> bool:
    """Heuristic: if both bounds are whole numbers, treat as integer param."""
    return low == int(low) and high == int(high)


def _sample_param(name: str, low: float, high: float) -> float:
    """Sample a single parameter value uniformly from its range."""
    if _is_integer_param(name, low, high):
        return float(random.randint(int(low), int(high)))
    return random.uniform(low, high)


def _round_param(name: str, value: float, low: float, high: float) -> float:
    """Clamp and optionally round a parameter value."""
    value = max(low, min(high, value))
    if _is_integer_param(name, low, high):
        return float(round(value))
    return round(value, 4)


# ---------------------------------------------------------------------------
# TPE-inspired sampler
# ---------------------------------------------------------------------------


class _TPESampler:
    """Simple TPE-inspired sampler.

    Splits observed trials into "good" (top quantile by objective) and "bad"
    (rest).  New candidates are sampled from a Gaussian fitted to the "good"
    group, accepted if the ratio l(x)/g(x) is favourable.
    """

    def __init__(
        self,
        param_space: dict[str, tuple[float, float]],
        gamma: float = 0.25,
    ) -> None:
        self._space = param_space
        self._gamma = gamma  # fraction considered "good"

    def sample_random(self) -> dict[str, float]:
        """Uniform random sample (used for initial exploration)."""
        return {
            name: _sample_param(name, lo, hi)
            for name, (lo, hi) in self._space.items()
        }

    def sample_guided(
        self,
        trials: list[TrialResult],
    ) -> dict[str, float]:
        """Sample a new point guided by past observations."""
        n_good = max(1, int(len(trials) * self._gamma))
        sorted_trials = sorted(trials, key=lambda t: t.score, reverse=True)
        good = sorted_trials[:n_good]
        bad = sorted_trials[n_good:]

        params: dict[str, float] = {}
        for name, (lo, hi) in self._space.items():
            good_vals = np.array([t.params[name] for t in good])
            mu_good = float(np.mean(good_vals))
            std_good = float(np.std(good_vals)) + 1e-6

            # Sample from good distribution
            candidate = float(np.random.normal(mu_good, std_good))
            candidate = _round_param(name, candidate, lo, hi)

            # Acceptance check: prefer points with high l(x)/g(x) ratio
            if len(bad) > 0:
                bad_vals = np.array([t.params[name] for t in bad])
                mu_bad = float(np.mean(bad_vals))
                std_bad = float(np.std(bad_vals)) + 1e-6

                l_x = norm.pdf(candidate, mu_good, std_good)
                g_x = norm.pdf(candidate, mu_bad, std_bad) + 1e-10

                # If ratio is poor, resample from good distribution
                if l_x / g_x < 0.5:
                    candidate = float(np.random.normal(mu_good, std_good * 0.5))
                    candidate = _round_param(name, candidate, lo, hi)

            params[name] = candidate

        return params


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------


def _extract_metric(result: BacktestResult, objective: str) -> float:
    """Extract the objective metric from a backtest result."""
    if objective == "sharpe_ratio":
        return result.sharpe_ratio
    if objective == "total_pnl":
        return result.total_pnl
    if objective == "win_rate":
        return result.win_rate
    return result.sharpe_ratio


class ParameterOptimizer:
    """Bayesian optimization for strategy parameters with Walk-Forward validation."""

    def __init__(self, session_factory: Any, okx_client: Any) -> None:
        self._session_factory = session_factory
        self._okx_client = okx_client

    async def optimize(
        self,
        strategy_name: str,
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        leverage: int,
        param_space: dict[str, tuple[float, float]] | None = None,
        n_iterations: int = 50,
        walk_forward_split: float = 0.7,
        objective: str = "sharpe_ratio",
        n_initial: int = 10,
    ) -> OptimizationResult:
        """Run Bayesian parameter optimization.

        1. Fetch candles once for the full period.
        2. Split into train / validation by walk_forward_split.
        3. Run n_iterations trials with TPE-guided sampling.
        4. Return the best parameters and all trial results.
        """
        log = logger.bind(
            strategy=strategy_name,
            pair=pair,
            n_iterations=n_iterations,
        )
        log.info("optimization_start", start=start_date.isoformat(), end=end_date.isoformat())

        # Resolve param space
        if param_space is None:
            param_space = DEFAULT_PARAM_SPACES.get(strategy_name, {})
        if not param_space:
            raise ValueError(
                f"No parameter space defined for strategy {strategy_name!r}. "
                "Provide param_space explicitly or add defaults to DEFAULT_PARAM_SPACES."
            )

        # Compute train/val split dates
        total_seconds = (end_date - start_date).total_seconds()
        split_seconds = total_seconds * walk_forward_split
        split_date = start_date + timedelta(seconds=split_seconds)

        train_start = start_date
        train_end = split_date
        val_start = split_date
        val_end = end_date

        log.info(
            "optimization_split",
            train=f"{train_start.isoformat()} -> {train_end.isoformat()}",
            val=f"{val_start.isoformat()} -> {val_end.isoformat()}",
        )

        # Fetch candles once for the entire period
        async with self._session_factory() as session:
            from app.exchange.data_collector import DataCollector

            collector = DataCollector(okx_client=self._okx_client, db_session=session)
            candle_count = await collector.fetch_historical_candles(
                pair=pair,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
            )
            await session.commit()
            log.info("optimization_candles_fetched", count=candle_count)

        # TPE sampler
        sampler = _TPESampler(param_space)
        trials: list[TrialResult] = []
        best_score = -math.inf
        best_params: dict[str, float] = {}

        for i in range(n_iterations):
            # Sample parameters
            if i < n_initial:
                params = sampler.sample_random()
            else:
                params = sampler.sample_guided(trials)

            # Run backtests on train and validation periods
            try:
                train_result = await self._run_single_backtest(
                    strategy_name, pair, timeframe,
                    train_start, train_end,
                    initial_balance, leverage, params,
                )
                val_result = await self._run_single_backtest(
                    strategy_name, pair, timeframe,
                    val_start, val_end,
                    initial_balance, leverage, params,
                )
            except Exception as exc:
                log.warning(
                    "optimization_trial_failed",
                    trial=i + 1,
                    params=params,
                    error=str(exc),
                )
                continue

            score = _extract_metric(val_result, objective)

            trial = TrialResult(
                trial_number=i + 1,
                params=params,
                train_sharpe=train_result.sharpe_ratio,
                train_pnl=train_result.total_pnl,
                train_win_rate=train_result.win_rate,
                val_sharpe=val_result.sharpe_ratio,
                val_pnl=val_result.total_pnl,
                val_win_rate=val_result.win_rate,
                score=score,
            )
            trials.append(trial)

            if score > best_score:
                best_score = score
                best_params = params.copy()

            # Log progress every 10 trials
            if (i + 1) % 10 == 0 or i == 0:
                log.info(
                    "optimization_progress",
                    trial=i + 1,
                    total=n_iterations,
                    best_score=round(best_score, 4),
                    best_params=best_params,
                )

        log.info(
            "optimization_complete",
            best_score=round(best_score, 4),
            best_params=best_params,
            total_trials=len(trials),
        )

        return OptimizationResult(
            strategy_name=strategy_name,
            pair=pair,
            best_params=best_params,
            best_score=best_score,
            total_trials=len(trials),
            trials=trials,
            train_period=f"{train_start.isoformat()} to {train_end.isoformat()}",
            val_period=f"{val_start.isoformat()} to {val_end.isoformat()}",
        )

    async def _run_single_backtest(
        self,
        strategy_name: str,
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        leverage: int,
        params: dict[str, float],
    ) -> BacktestResult:
        """Run a single backtest with given parameters. Uses its own DB session."""
        strategy_cls = registry.get(strategy_name)
        strategy: BaseStrategy = strategy_cls()
        strategy.configure(params)

        async with self._session_factory() as session:
            engine = BacktestEngine(db_session=session)
            result = await engine.run(
                strategy=strategy,
                pair=pair,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_balance=initial_balance,
                leverage=leverage,
            )
            await session.commit()

        return result
