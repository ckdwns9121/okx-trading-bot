"""Automated strategy validation pipeline.

Orchestrates: data collection → batch backtest → ranking → optimization of top N.
Designed to run as a background asyncio.Task with progress polling.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.backtest_engine import BacktestEngine, BacktestResult
from app.core.optimizer import ParameterOptimizer
from app.core.strategy_registry import StrategyRegistry
from app.exchange.data_collector import DataCollector
from app.logging_config import get_logger

logger = get_logger(__name__)

_RESULTS_DIR = Path(__file__).parent.parent.parent.parent / ".omc" / "validation-results"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrategyRanking:
    rank: int
    strategy_name: str
    pair: str
    timeframe: str
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_pnl: float
    trade_count: int
    composite_score: float


@dataclass
class OptimizedStrategy:
    strategy_name: str
    original_params: dict[str, float]
    optimized_params: dict[str, float]
    before_score: float
    after_score: float


@dataclass
class ValidationResult:
    run_id: str
    rankings: list[StrategyRanking]
    optimized: list[OptimizedStrategy]
    completed_at: str
    total_backtests: int
    duration_seconds: float


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def composite_score(sharpe: float, mdd: float, win_rate: float) -> float:
    """Weighted score with normalised Sharpe.

    All three terms are in [0, 1] so the result is in [0, 1].
    """
    norm_sharpe = _clamp(sharpe + 1.0, 0.0, 4.0) / 4.0
    norm_mdd = 1.0 - _clamp(mdd, 0.0, 1.0)
    norm_wr = _clamp(win_rate, 0.0, 1.0)
    return norm_sharpe * 0.4 + norm_mdd * 0.35 + norm_wr * 0.25


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ValidationPipeline:
    """Run a full strategy validation and store results."""

    def __init__(
        self,
        okx_client: Any,
        session_factory: async_sessionmaker,
        registry: StrategyRegistry,
    ) -> None:
        self._okx = okx_client
        self._sf = session_factory
        self._registry = registry
        self.progress: dict[str, Any] = {
            "run_id": "",
            "phase": "idle",
            "pct": 0,
            "message": "",
            "started_at": None,
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run(
        self,
        pairs: list[str],
        timeframes: list[str],
        initial_balance: float = 10_000.0,
        leverage: int = 1,
        lookback_days: int = 180,
        top_n: int = 3,
        n_iterations: int = 30,
    ) -> ValidationResult:
        run_id = uuid.uuid4().hex[:12]
        self.progress.update(run_id=run_id, phase="collecting", pct=0,
                             message="데이터 수집 중…", started_at=datetime.now(timezone.utc).isoformat())
        t0 = time.monotonic()

        # Use naive UTC datetimes to match the DB column type (TIMESTAMP WITHOUT TIME ZONE)
        end_date = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=lookback_days)

        strategy_names = self._registry.list_all()
        log = logger.bind(run_id=run_id)
        log.info("validation_start", strategies=len(strategy_names), pairs=pairs, timeframes=timeframes)

        # ── Phase 1: Collect candles ─────────────────────────────
        total_combos = len(pairs) * len(timeframes)
        for idx, pair in enumerate(pairs):
            for jdx, tf in enumerate(timeframes):
                combo_num = idx * len(timeframes) + jdx + 1
                self.progress.update(
                    pct=int(combo_num / total_combos * 15),
                    message=f"캔들 수집: {pair} {tf} ({combo_num}/{total_combos})",
                )
                try:
                    async with self._sf() as session:
                        collector = DataCollector(self._okx, session)
                        await collector.fetch_historical_candles(pair, tf, start_date, end_date)
                        await session.commit()
                except Exception as exc:
                    log.error("validation_collect_error", pair=pair, tf=tf, error=str(exc))

        # ── Phase 2: Backtest all combos ─────────────────────────
        self.progress.update(phase="backtesting", pct=15, message="백테스트 실행 중…")
        all_results: list[tuple[str, str, str, BacktestResult]] = []
        total_runs = len(strategy_names) * total_combos
        done_runs = 0

        for sname in strategy_names:
            try:
                strategy_cls = self._registry.get(sname)
            except KeyError:
                continue

            for pair in pairs:
                for tf in timeframes:
                    done_runs += 1
                    self.progress.update(
                        pct=15 + int(done_runs / total_runs * 50),
                        message=f"백테스트: {sname} / {pair} {tf} ({done_runs}/{total_runs})",
                    )
                    try:
                        strategy = strategy_cls()
                        strategy.configure({})
                        async with self._sf() as session:
                            engine = BacktestEngine(session)
                            result = await engine.run(
                                strategy=strategy,
                                pair=pair,
                                timeframe=tf,
                                start_date=start_date,
                                end_date=end_date,
                                initial_balance=initial_balance,
                                leverage=leverage,
                                persist=False,
                            )
                        all_results.append((sname, pair, tf, result))
                    except Exception as exc:
                        log.warning("validation_backtest_skip", strategy=sname, pair=pair, tf=tf, error=str(exc))

        # ── Phase 3: Rank ────────────────────────────────────────
        self.progress.update(phase="ranking", pct=65, message="전략 순위 산출 중…")

        rankings: list[StrategyRanking] = []
        for sname, pair, tf, r in all_results:
            score = composite_score(r.sharpe_ratio, r.max_drawdown, r.win_rate)
            rankings.append(StrategyRanking(
                rank=0,
                strategy_name=sname,
                pair=pair,
                timeframe=tf,
                sharpe_ratio=round(r.sharpe_ratio, 4),
                max_drawdown=round(r.max_drawdown, 4),
                win_rate=round(r.win_rate, 4),
                total_pnl=round(r.total_pnl, 2),
                trade_count=r.trade_count,
                composite_score=round(score, 4),
            ))

        rankings.sort(key=lambda r: r.composite_score, reverse=True)
        for i, r in enumerate(rankings):
            r.rank = i + 1

        # ── Phase 4: Optimize top N ──────────────────────────────
        self.progress.update(phase="optimizing", pct=70, message="상위 전략 최적화 중…")

        # Deduplicate by strategy name — pick best combo per strategy
        seen: set[str] = set()
        top_entries: list[StrategyRanking] = []
        for r in rankings:
            if r.strategy_name not in seen and len(top_entries) < top_n:
                seen.add(r.strategy_name)
                top_entries.append(r)

        optimized: list[OptimizedStrategy] = []
        for oi, entry in enumerate(top_entries):
            self.progress.update(
                pct=70 + int((oi + 1) / len(top_entries) * 25),
                message=f"최적화: {entry.strategy_name} ({oi + 1}/{len(top_entries)})",
            )
            try:
                optimizer = ParameterOptimizer(self._sf, self._okx)
                opt_result = await optimizer.optimize(
                    strategy_name=entry.strategy_name,
                    pair=entry.pair,
                    timeframe=entry.timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    initial_balance=initial_balance,
                    leverage=leverage,
                    n_iterations=n_iterations,
                )
                optimized.append(OptimizedStrategy(
                    strategy_name=entry.strategy_name,
                    original_params={},
                    optimized_params={k: round(v, 4) for k, v in opt_result.best_params.items()},
                    before_score=entry.composite_score,
                    after_score=round(opt_result.best_score, 4),
                ))
            except Exception as exc:
                log.error("validation_optimize_error", strategy=entry.strategy_name, error=str(exc))

        # ── Done ─────────────────────────────────────────────────
        elapsed = round(time.monotonic() - t0, 1)
        result = ValidationResult(
            run_id=run_id,
            rankings=rankings,
            optimized=optimized,
            completed_at=datetime.now(timezone.utc).isoformat(),
            total_backtests=len(all_results),
            duration_seconds=elapsed,
        )

        self.progress.update(phase="complete", pct=100, message=f"완료 — {elapsed}초 소요")
        log.info("validation_complete", backtests=len(all_results), elapsed=elapsed)

        # Persist to JSON
        self._save_results(result)
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_results(self, result: ValidationResult) -> None:
        try:
            _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            path = _RESULTS_DIR / "latest.json"
            data = {
                "run_id": result.run_id,
                "rankings": [asdict(r) for r in result.rankings],
                "optimized": [asdict(o) for o in result.optimized],
                "completed_at": result.completed_at,
                "total_backtests": result.total_backtests,
                "duration_seconds": result.duration_seconds,
            }
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            logger.info("validation_results_saved", path=str(path))
        except Exception as exc:
            logger.error("validation_results_save_error", error=str(exc))

    @staticmethod
    def load_latest() -> Optional[dict[str, Any]]:
        path = _RESULTS_DIR / "latest.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
