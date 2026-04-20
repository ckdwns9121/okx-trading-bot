"""In-process analysis orchestrator for analysis-skill requests.

The runner composes existing optimizer and backtest engines without HTTP calls.
It applies explicit run-risk controls, computes recommendation scores, and
attaches replay validation for the top candidate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.backtest_engine import BacktestEngine, BacktestResult
from app.core.optimizer import ParameterOptimizer
from app.core.strategy_base import BaseStrategy
from app.core.strategy_registry import registry as strategy_registry
from app.logging_config import get_logger
from app.models.analysis_skill import AnalysisRequest
from app.models.analysis_skill import CANONICAL_METRIC_KEYS
from app.core import analysis_scoring

logger = get_logger(__name__)


def replay_passes_policy(original: dict[str, float], replay: dict[str, float]) -> bool:
    """Replay policy used for top-1 candidate reproducibility checks."""
    return (
        abs(replay["total_pnl"] - original["total_pnl"]) / max(abs(original["total_pnl"]), 1.0)
        <= 0.05
        and abs(replay["sharpe_ratio"] - original["sharpe_ratio"]) <= 0.15
        and replay["trade_count"] >= 0.9 * original["trade_count"]
    )


@dataclass
class MetricsByWindowResult:
    train: dict[str, float]
    val: dict[str, float]
    holdout: dict[str, float]


@dataclass
class RecommendationResult:
    rank: int
    params: dict[str, float]
    score: float
    metrics_by_window: MetricsByWindowResult
    baseline_delta_by_window: dict[str, dict[str, float]]
    replay_pass: bool
    replay_delta: dict[str, float]


@dataclass
class AnalysisRunResult:
    run_id: str
    status: str
    failures: dict[str, Any]
    baseline: dict[str, MetricsByWindowResult]
    recommendations: list[RecommendationResult]


class AnalysisExperimentRunner:
    def __init__(self, okx_client: Any, session_factory: Any) -> None:
        self._okx_client = okx_client
        self._session_factory = session_factory

    async def _ensure_candles(self, pair: str, timeframe: str, start_dt: datetime, end_dt: datetime) -> None:
        async with self._session_factory() as session:
            from app.exchange.data_collector import DataCollector

            collector = DataCollector(okx_client=self._okx_client, db_session=session)
            await collector.fetch_historical_candles(
                pair=pair,
                timeframe=timeframe,
                start_date=start_dt,
                end_date=end_dt,
            )
            await session.commit()

    @staticmethod
    def _params_hash(params: dict[str, Any]) -> str:
        payload = json.dumps({k: float(v) for k, v in sorted(params.items())}, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _bt_metrics(bt: BacktestResult) -> dict[str, float]:
        return {
            "total_pnl": float(bt.total_pnl),
            "sharpe_ratio": float(bt.sharpe_ratio),
            "max_drawdown": float(bt.max_drawdown),
            "win_rate": float(bt.win_rate),
            "trade_count": float(bt.trade_count),
        }

    async def _run_backtest_once(
        self,
        strategy_name: str,
        params: dict[str, float],
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        assumptions: Any,
        *,
        timeout_sec: int,
        retry_per_failed_job: int,
    ) -> BacktestResult:
        if end_date <= start_date:
            raise ValueError("window end must be after start")

        last_exc: Exception | None = None
        for attempt in range(retry_per_failed_job + 1):
            try:
                async def _one_run() -> BacktestResult:
                    strategy_cls = strategy_registry.get(strategy_name)
                    strategy: BaseStrategy = strategy_cls()
                    strategy.configure(dict(params))

                    async with self._session_factory() as session:
                        engine = BacktestEngine(db_session=session)
                        result = await engine.run(
                            strategy=strategy,
                            pair=pair,
                            timeframe=timeframe,
                            start_date=start_date,
                            end_date=end_date,
                            initial_balance=assumptions.initial_balance,
                            leverage=assumptions.leverage,
                            fee_rate=assumptions.fee_rate,
                            slippage_pct=assumptions.slippage_pct,
                            cooldown_candles=assumptions.cooldown_candles,
                            funding_rate_per_8h=assumptions.funding_rate_per_8h,
                            liquidity_impact_factor=assumptions.liquidity_impact_factor,
                            maintenance_margin_ratio=assumptions.maintenance_margin_ratio,
                            liquidation_fee_pct=assumptions.liquidation_fee_pct,
                            persist=False,
                        )
                        await session.commit()
                    return result

                return await asyncio.wait_for(_one_run(), timeout=timeout_sec)
            except Exception as exc:  # includes timeout and runtime failures
                last_exc = exc
                if attempt >= retry_per_failed_job:
                    break
        raise last_exc if last_exc is not None else RuntimeError("backtest failed")

    async def run(self, request: AnalysisRequest) -> AnalysisRunResult:
        run_id = hashlib.sha1(
            f"{request.strategy_name}:{request.pair}:{request.timeframe}:{datetime.utcnow().isoformat()}".encode("utf-8")
        ).hexdigest()[:12]

        windows = {w.name: w for w in request.windows}
        run_limits = request.run_limits

        log = logger.bind(
            run_id=run_id,
            strategy_name=request.strategy_name,
        )
        log.info(
            "analysis_skill_run_started",
            status="started",
            run_id=run_id,
            strategy_name=request.strategy_name,
        )

        # Ensure required candle span exists once.
        start_dt = min(datetime.fromisoformat(windows["train"].start), datetime.fromisoformat(windows["val"].start), datetime.fromisoformat(windows["holdout"].start))
        end_dt = max(datetime.fromisoformat(windows["train"].end), datetime.fromisoformat(windows["val"].end), datetime.fromisoformat(windows["holdout"].end))
        await self._ensure_candles(request.pair, request.timeframe, start_dt, end_dt)

        # ── Baseline
        baseline_by_window: dict[str, dict[str, float]] = {}
        for name, win in windows.items():
            bt = await self._run_backtest_once(
                request.baseline_strategy_name,
                {},
                request.pair,
                request.timeframe,
                datetime.fromisoformat(win.start),
                datetime.fromisoformat(win.end),
                request.assumptions,
                timeout_sec=run_limits.timeout_sec,
                retry_per_failed_job=run_limits.retry_per_failed_job,
            )
            baseline_by_window[name] = self._bt_metrics(bt)

        baseline_metrics = MetricsByWindowResult(
            train=baseline_by_window["train"],
            val=baseline_by_window["val"],
            holdout=baseline_by_window["holdout"],
        )

        # ── Candidate generation via in-process optimizer
        # Use train+val as full optimization region.
        optimizer = ParameterOptimizer(self._session_factory, self._okx_client)
        opt_result = await optimizer.optimize(
            strategy_name=request.strategy_name,
            pair=request.pair,
            timeframe=request.timeframe,
            start_date=datetime.fromisoformat(windows["train"].start),
            end_date=datetime.fromisoformat(windows["val"].end),
            initial_balance=request.assumptions.initial_balance,
            leverage=request.assumptions.leverage,
            param_space=request.search_space,
            n_iterations=min(run_limits.max_combinations, 500),
            walk_forward_split=0.7,
            objective="sharpe_ratio",
        )

        # Keep the best N unique param sets from optimizer trials.
        seen_params: set[str] = set()
        ranked_candidates: list[tuple[float, dict[str, float]]] = []
        for trial in opt_result.trials:
            key = self._params_hash(trial.params)
            if key in seen_params:
                continue
            seen_params.add(key)
            ranked_candidates.append((trial.score, trial.params))

        ranked_candidates.sort(key=lambda item: item[0], reverse=True)

        recommendations: list[RecommendationResult] = []
        attempted = 0
        failed = 0
        for rank, (_, params) in enumerate(ranked_candidates[: request.top_k], start=1):
            params_hash = self._params_hash(params)
            cand_metrics: dict[str, dict[str, float]] = {}
            try:
                for name in ("train", "val", "holdout"):
                    win = windows[name]
                    attempted += 1
                    bt = await self._run_backtest_once(
                        request.strategy_name,
                        params,
                        request.pair,
                        request.timeframe,
                        datetime.fromisoformat(win.start),
                        datetime.fromisoformat(win.end),
                        request.assumptions,
                        timeout_sec=run_limits.timeout_sec,
                        retry_per_failed_job=run_limits.retry_per_failed_job,
                    )
                    attempted += 1
                    cand_metrics[name] = self._bt_metrics(bt)
                    baseline_delta = {
                        k: cand_metrics[name][k] - baseline_by_window[name][k] for k in CANONICAL_METRIC_KEYS
                    }
                    log.info(
                        "analysis_candidate_evaluated",
                        run_id=run_id,
                        strategy_name=request.strategy_name,
                        params_hash=params_hash,
                        window=name,
                        status="evaluated",
                        score=0.0,
                        recommendation_rank=rank,
                        degraded_mode=False,
                        failure_ratio=0.0,
                        baseline_delta={k: float(v) for k, v in baseline_delta.items()},
                        replay_delta={},
                    )

                # Replay check for top candidate only.
                replay_pass = True
                replay_delta: dict[str, float] = {}
                if rank == 1:
                    win = windows["holdout"]
                    first = cand_metrics["holdout"]
                    attempted += 1
                    replay = await self._run_backtest_once(
                        request.strategy_name,
                        params,
                        request.pair,
                        request.timeframe,
                        datetime.fromisoformat(win.start),
                        datetime.fromisoformat(win.end),
                        request.assumptions,
                        timeout_sec=run_limits.timeout_sec,
                        retry_per_failed_job=run_limits.retry_per_failed_job,
                    )
                    replay_metrics = self._bt_metrics(replay)

                    attempted += 1
                    replay_delta = {
                        k: replay_metrics[k] - first[k] for k in CANONICAL_METRIC_KEYS
                    }
                    original = first
                    replay_pass = replay_passes_policy(first, replay_metrics)
                    log.info(
                        "analysis_replay_completed",
                        run_id=run_id,
                        strategy_name=request.strategy_name,
                        params_hash=params_hash,
                        window="holdout",
                        score=0.0,
                        replay_delta={k: float(v) for k, v in replay_delta.items()},
                        baseline_delta={},
                        recommendation_rank=rank,
                        status="ok" if replay_pass else "warning",
                        degraded_mode=not replay_pass,
                        failure_ratio=0.0,
                    )

                window_scores = analysis_scoring.score_candidate(cand_metrics)
                recommendations.append(
                    RecommendationResult(
                        rank=rank,
                        params={k: float(v) for k, v in params.items()},
                        score=window_scores,
                        metrics_by_window=MetricsByWindowResult(
                            train=cand_metrics["train"],
                            val=cand_metrics["val"],
                            holdout=cand_metrics["holdout"],
                        ),
                        baseline_delta_by_window={
                            name: {
                                k: cand_metrics[name][k] - baseline_by_window[name][k]
                                for k in CANONICAL_METRIC_KEYS
                            }
                            for name in ("train", "val", "holdout")
                        },
                        replay_pass=bool(replay_pass),
                        replay_delta={k: float(v) for k, v in replay_delta.items()},
                    )
                )

            except Exception:
                failed += 1
                window_name = name if "name" in locals() else "unknown"
                log.warning(
                    "analysis_candidate_evaluated",
                    run_id=run_id,
                    strategy_name=request.strategy_name,
                    params_hash=params_hash,
                    window=window_name,
                    status="failed",
                    score=0.0,
                    recommendation_rank=rank,
                    degraded_mode=True,
                    failure_ratio=0.0,
                    baseline_delta={},
                    replay_delta={},
                    error="candidate_backtest_failed",
                )
                if failed / max(1, attempted) > run_limits.partial_failure_threshold:
                    break

        attempted_count = max(1, attempted)
        failure_ratio = failed / max(1, attempted)
        if attempted == 0:
            failure_ratio = 1.0

        if failure_ratio > run_limits.partial_failure_threshold:
            status = "failed"
            degraded_mode = True
        elif failed > 0:
            status = "warning"
            degraded_mode = True
        else:
            status = "ok"
            degraded_mode = False

        # Ensure recommendations are re-ranked by score only after candidate eval.
        recommendations.sort(key=lambda r: r.score, reverse=True)
        for i, rec in enumerate(recommendations, start=1):
            rec.rank = i

        log.info(
            "analysis_skill_run_completed",
            run_id=run_id,
            strategy_name=request.strategy_name,
            status=status,
            recommendation_count=len(recommendations),
            failure_ratio=float(failure_ratio),
            degraded_mode=degraded_mode,
            window="summary",
            score=float(recommendations[0].score) if recommendations else 0.0,
            replay_delta={},
            baseline_delta={},
            recommendation_rank=0,
            params_hash="",
            status_summary=status,
        )

        return AnalysisRunResult(
            run_id=run_id,
            status=status,
            failures={
                "failed_combinations": failed,
                "failure_ratio": float(failure_ratio),
                "degraded_mode": degraded_mode,
            },
            baseline={"metrics_by_window": {
                "train": baseline_metrics.train,
                "val": baseline_metrics.val,
                "holdout": baseline_metrics.holdout,
            }},
            recommendations=recommendations,
        )
