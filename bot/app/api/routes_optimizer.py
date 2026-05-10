"""Optimizer API routes.

POST /api/optimize                          — run parameter optimization
GET  /api/optimize/param-space/{strategy}   — get default param space for a strategy
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["optimizer"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class OptimizeRequest(BaseModel):
    strategy_name: str = Field(..., description="Registered strategy name")
    pair: str = Field(..., description="Instrument ID, e.g. BTC-USDT-SWAP")
    timeframe: str = Field(..., description="Candle timeframe, e.g. 1H, 15m")
    start_date: str = Field(..., description="ISO-8601 start date")
    end_date: str = Field(..., description="ISO-8601 end date")
    initial_balance: float = Field(default=10000.0, gt=0)
    leverage: int = Field(default=1, ge=1, le=125)
    n_iterations: int = Field(default=50, ge=10, le=200)
    walk_forward_split: float = Field(default=0.7, ge=0.5, le=0.9)
    objective: str = Field(default="sharpe_ratio")

    @field_validator("start_date", "end_date")
    @classmethod
    def _parse_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 date: {v!r}") from exc
        return v

    @field_validator("objective")
    @classmethod
    def _validate_objective(cls, v: str) -> str:
        allowed = {"sharpe_ratio", "total_pnl", "win_rate"}
        if v not in allowed:
            raise ValueError(f"objective must be one of {allowed}, got {v!r}")
        return v


class TrialResultOut(BaseModel):
    trial_number: int
    params: dict[str, float]
    train_sharpe: float
    train_pnl: float
    train_win_rate: float
    val_sharpe: float
    val_pnl: float
    val_win_rate: float
    score: float


class OptimizationResultOut(BaseModel):
    strategy_name: str
    pair: str
    best_params: dict[str, float]
    best_score: float
    total_trials: int
    trials: list[TrialResultOut]
    train_period: str
    val_period: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/optimize",
    response_model=OptimizationResultOut,
    summary="Run parameter optimization for a strategy",
)
async def run_optimization(
    body: OptimizeRequest,
    request: Request,
) -> OptimizationResultOut:
    """Validate inputs, run the optimizer, and return results."""
    # Validate strategy exists
    strat_registry = request.app.state.strategy_registry
    if body.strategy_name not in strat_registry.list_all():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown strategy {body.strategy_name!r}. Available: {strat_registry.list_all()}",
        )

    start_dt = datetime.fromisoformat(body.start_date).replace(tzinfo=None)
    end_dt = datetime.fromisoformat(body.end_date).replace(tzinfo=None)

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be after start_date",
        )

    log = logger.bind(strategy=body.strategy_name, pair=body.pair)
    log.info("optimization_request_received", iterations=body.n_iterations)

    from app.core.optimizer import ParameterOptimizer
    from app.db.database import AsyncSessionLocal
    from app.exchange.public_market_data import OKXPublicMarketData

    market_data = OKXPublicMarketData()

    try:
        optimizer = ParameterOptimizer(
            session_factory=AsyncSessionLocal,
            okx_client=market_data,
        )
        result = await optimizer.optimize(
            strategy_name=body.strategy_name,
            pair=body.pair,
            timeframe=body.timeframe,
            start_date=start_dt,
            end_date=end_dt,
            initial_balance=body.initial_balance,
            leverage=body.leverage,
            n_iterations=body.n_iterations,
            walk_forward_split=body.walk_forward_split,
            objective=body.objective,
        )
    finally:
        await market_data.close()

    trials_out = [
        TrialResultOut(
            trial_number=t.trial_number,
            params=t.params,
            train_sharpe=round(t.train_sharpe, 4),
            train_pnl=round(t.train_pnl, 2),
            train_win_rate=round(t.train_win_rate, 4),
            val_sharpe=round(t.val_sharpe, 4),
            val_pnl=round(t.val_pnl, 2),
            val_win_rate=round(t.val_win_rate, 4),
            score=round(t.score, 4),
        )
        for t in result.trials
    ]

    return OptimizationResultOut(
        strategy_name=result.strategy_name,
        pair=result.pair,
        best_params={k: round(v, 4) for k, v in result.best_params.items()},
        best_score=round(result.best_score, 4),
        total_trials=result.total_trials,
        trials=trials_out,
        train_period=result.train_period,
        val_period=result.val_period,
    )


@router.get(
    "/optimize/param-space/{strategy_name}",
    summary="Get default parameter space for a strategy",
)
async def get_param_space(
    strategy_name: str,
    request: Request,
) -> dict[str, list[float]]:
    """Return the default parameter ranges for a given strategy."""
    from app.core.optimizer import DEFAULT_PARAM_SPACES

    strat_registry = request.app.state.strategy_registry
    if strategy_name not in strat_registry.list_all():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown strategy {strategy_name!r}. Available: {strat_registry.list_all()}",
        )

    space = DEFAULT_PARAM_SPACES.get(strategy_name, {})
    # Convert tuples to lists for JSON serialization
    return {k: list(v) for k, v in space.items()}
