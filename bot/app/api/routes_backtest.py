"""Backtest API routes.

POST /api/backtest        — submit a new backtest run
GET  /api/backtest        — list all backtest runs
GET  /api/backtest/{run_id} — retrieve a single run with its trades
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.logging_config import get_logger
from app.models.backtest_run import BacktestRun
from app.models.trade import Trade

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["backtest"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    strategy_name: str = Field(..., description="Registered strategy name")
    pair: str = Field(..., description="Instrument ID, e.g. BTC-USDT-SWAP")
    timeframe: str = Field(..., description="Candle timeframe, e.g. 1H, 15m")
    start_date: str = Field(..., description="ISO-8601 start date, e.g. 2024-01-01")
    end_date: str = Field(..., description="ISO-8601 end date, e.g. 2024-06-01")
    initial_balance: float = Field(..., gt=0, description="Starting balance in USD")
    leverage: int = Field(..., ge=1, le=125, description="Futures leverage")
    fee_rate: float = Field(default=0.0005, ge=0, description="Taker fee rate, e.g. 0.0005")
    slippage_pct: float = Field(default=0.0, ge=0, description="Slippage as decimal, e.g. 0.001")
    cooldown_candles: int = Field(default=0, ge=0, description="Number of candles to skip re-entry after stop-loss")
    funding_rate_per_8h: float = Field(
        default=0.0,
        description="Perpetual funding rate applied every 8h in simulation (positive: longs pay / shorts receive).",
    )
    liquidity_impact_factor: float = Field(
        default=0.0,
        ge=0,
        description="Liquidity impact coefficient for dynamic slippage model.",
    )
    maintenance_margin_ratio: float = Field(
        default=0.005,
        ge=0,
        le=1,
        description="Maintenance margin ratio used for simplified liquidation simulation.",
    )
    liquidation_fee_pct: float = Field(
        default=0.002,
        ge=0,
        description="Additional fee applied on liquidation exits (as fraction of notional).",
    )
    parameters_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional strategy parameters passed to strategy.configure(...)",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _parse_date(cls, v: str) -> str:
        # Validate that the string is parseable; actual datetime conversion happens in the handler.
        try:
            datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 date: {v!r}") from exc
        return v


class BacktestSubmitResponse(BaseModel):
    run_id: str
    status: str = "running"


class TradeOut(BaseModel):
    id: int
    strategy_name: str
    pair: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    leverage: int
    pnl: Optional[float]
    pnl_pct: Optional[float]
    fee: float
    entry_time: datetime
    exit_time: Optional[datetime]
    status: str
    source: str

    model_config = {"from_attributes": True}


class BacktestRunOut(BaseModel):
    id: uuid.UUID
    strategy_name: str
    pair: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    leverage: int
    fee_rate: float
    slippage_pct: float
    total_pnl: Optional[float]
    win_rate: Optional[float]
    max_drawdown: Optional[float]
    sharpe_ratio: Optional[float]
    trade_count: Optional[int]
    parameters_json: Optional[dict[str, Any]]
    created_at: datetime
    trades: list[TradeOut] = Field(default_factory=list)
    equity_curve: list[dict] = Field(default_factory=list)
    buy_hold_pnl: Optional[float] = None
    buy_hold_return_pct: Optional[float] = None

    model_config = {"from_attributes": True}


class BacktestRunSummary(BaseModel):
    id: uuid.UUID
    strategy_name: str
    pair: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    leverage: int
    total_pnl: Optional[float]
    win_rate: Optional[float]
    max_drawdown: Optional[float]
    sharpe_ratio: Optional[float]
    trade_count: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/backtest",
    response_model=BacktestSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new backtest run",
)
async def submit_backtest(
    body: BacktestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> BacktestSubmitResponse:
    """Validate the request, create the BacktestRun row, and kick off a background task."""
    # Validate strategy exists in registry.
    registry = request.app.state.strategy_registry
    if body.strategy_name not in registry.list_all():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown strategy {body.strategy_name!r}. Available: {registry.list_all()}",
        )

    start_dt = datetime.fromisoformat(body.start_date).replace(tzinfo=None)
    end_dt = datetime.fromisoformat(body.end_date).replace(tzinfo=None)

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be after start_date",
        )

    log = logger.bind(strategy=body.strategy_name, pair=body.pair)
    log.info("backtest_submitted")

    # Run synchronously — simpler and avoids session/transaction issues.
    # Backtest engine handles its own DB persistence.
    from app.db.database import AsyncSessionLocal
    from app.core.backtest_engine import BacktestEngine
    from app.core.strategy_registry import registry as strat_registry
    from app.exchange.data_collector import DataCollector
    from app.exchange.public_market_data import OKXPublicMarketData

    market_data = OKXPublicMarketData()

    async with AsyncSessionLocal() as session:
        try:
            collector = DataCollector(okx_client=market_data, db_session=session)
            candle_count = await collector.fetch_historical_candles(
                pair=body.pair, timeframe=body.timeframe,
                start_date=start_dt, end_date=end_dt,
            )
            await session.commit()
            log.info("candles_fetched", count=candle_count)
        finally:
            await market_data.close()

        strategy_cls = strat_registry.get(body.strategy_name)
        strategy_inst = strategy_cls()
        strategy_inst.configure(body.parameters_json or {})

        engine = BacktestEngine(db_session=session)
        bt_result = await engine.run(
            strategy=strategy_inst,
            pair=body.pair,
            timeframe=body.timeframe,
            start_date=start_dt,
            end_date=end_dt,
            initial_balance=body.initial_balance,
            leverage=body.leverage,
            fee_rate=body.fee_rate,
            slippage_pct=body.slippage_pct,
            cooldown_candles=body.cooldown_candles,
            funding_rate_per_8h=body.funding_rate_per_8h,
            liquidity_impact_factor=body.liquidity_impact_factor,
            maintenance_margin_ratio=body.maintenance_margin_ratio,
            liquidation_fee_pct=body.liquidation_fee_pct,
        )

        log.info("backtest_complete", pnl=bt_result.total_pnl, trades=bt_result.trade_count)

        # Store equity curve and analytics in the run's parameters_json
        from sqlalchemy import update as sql_update
        from app.models.backtest_run import BacktestRun as BacktestRunModel
        equity_data = [
            {"index": i, "balance": round(b, 2), "drawdown": round(d, 4)}
            for i, (b, d) in enumerate(zip(bt_result.balance_series, bt_result.drawdown_series))
        ]
        await session.execute(
            sql_update(BacktestRunModel).where(BacktestRunModel.id == bt_result.run_id).values(
                parameters_json={
                    "equity_curve": equity_data,
                    "buy_hold_pnl": bt_result.buy_hold_pnl,
                    "buy_hold_return_pct": bt_result.buy_hold_return_pct,
                }
            )
        )
        await session.commit()

    return BacktestSubmitResponse(run_id=str(bt_result.run_id))


@router.get(
    "/backtest",
    response_model=list[BacktestRunSummary],
    summary="List all backtest runs",
)
async def list_backtest_runs(
    db: AsyncSession = Depends(get_db),
) -> list[BacktestRunSummary]:
    result = await db.execute(
        select(BacktestRun).order_by(BacktestRun.created_at.desc())
    )
    runs = result.scalars().all()
    return [BacktestRunSummary.model_validate(r) for r in runs]


class SensitivityRequest(BaseModel):
    strategy_name: str
    pair: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float = 10000.0
    leverage: int = 1
    fee_rates: list[float] = Field(default=[0.0002, 0.0005, 0.001, 0.002], max_length=10)
    slippage_pcts: list[float] = Field(default=[0.0, 0.025, 0.05, 0.1], max_length=10)


@router.post(
    "/backtest/sensitivity",
    summary="Fee/slippage sensitivity analysis",
)
async def sensitivity_analysis(
    body: SensitivityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from app.core.backtest_engine import BacktestEngine
    from app.core.strategy_registry import registry as strat_registry
    from app.exchange.data_collector import DataCollector
    from app.exchange.public_market_data import OKXPublicMarketData
    from app.db.database import AsyncSessionLocal

    registry = request.app.state.strategy_registry
    if body.strategy_name not in registry.list_all():
        raise HTTPException(status_code=422, detail=f"Unknown strategy {body.strategy_name!r}")

    start_dt = datetime.fromisoformat(body.start_date).replace(tzinfo=None)
    end_dt = datetime.fromisoformat(body.end_date).replace(tzinfo=None)

    # Fetch candles once
    market_data = OKXPublicMarketData()
    async with AsyncSessionLocal() as session:
        try:
            collector = DataCollector(okx_client=market_data, db_session=session)
            await collector.fetch_historical_candles(
                pair=body.pair, timeframe=body.timeframe,
                start_date=start_dt, end_date=end_dt,
            )
            await session.commit()
        finally:
            await market_data.close()

    results = []
    for fee in body.fee_rates:
        for slip in body.slippage_pcts:
            async with AsyncSessionLocal() as session:
                strategy_cls = strat_registry.get(body.strategy_name)
                strategy_inst = strategy_cls()
                strategy_inst.configure({})
                engine = BacktestEngine(db_session=session)
                bt = await engine.run(
                    strategy=strategy_inst, pair=body.pair, timeframe=body.timeframe,
                    start_date=start_dt, end_date=end_dt,
                    initial_balance=body.initial_balance, leverage=body.leverage,
                    fee_rate=fee, slippage_pct=slip, persist=False,
                )
                results.append({
                    "fee_rate": fee, "slippage_pct": slip,
                    "total_pnl": round(bt.total_pnl, 2),
                    "sharpe_ratio": round(bt.sharpe_ratio, 4),
                    "win_rate": round(bt.win_rate, 4),
                    "trade_count": bt.trade_count,
                    "final_balance": round(bt.final_balance, 2),
                })
    return results


@router.get(
    "/backtest/{run_id}",
    response_model=BacktestRunOut,
    summary="Get a backtest run with its trades",
)
async def get_backtest_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BacktestRunOut:
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")

    trades_result = await db.execute(
        select(Trade).where(Trade.backtest_run_id == run_id).order_by(Trade.entry_time)
    )
    trades = trades_result.scalars().all()

    out = BacktestRunOut.model_validate(run)
    out.trades = [TradeOut.model_validate(t) for t in trades]
    params = run.parameters_json or {}
    out.equity_curve = params.get("equity_curve", [])
    out.buy_hold_pnl = params.get("buy_hold_pnl")
    out.buy_hold_return_pct = params.get("buy_hold_return_pct")
    return out


@router.get(
    "/backtest/{run_id}/analytics",
    summary="Get detailed trade analytics for a backtest run",
)
async def get_backtest_analytics(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.core.analytics import compute_trade_analytics
    from dataclasses import asdict

    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades_result = await db.execute(
        select(Trade).where(Trade.backtest_run_id == run_id).order_by(Trade.entry_time)
    )
    trades = trades_result.scalars().all()
    analytics = compute_trade_analytics(
        [{"pnl": t.pnl or 0.0, "entry_time": t.entry_time, "exit_time": t.exit_time or t.entry_time} for t in trades],
        run.initial_balance,
    )
    result_dict = asdict(analytics)
    # Convert inf to None for JSON serialization
    for k, v in result_dict.items():
        if isinstance(v, float) and (v == float("inf") or v == float("-inf")):
            result_dict[k] = None
    return result_dict


@router.post(
    "/backtest/{run_id}/monte-carlo",
    summary="Run Monte Carlo simulation on backtest trades",
)
async def run_monte_carlo(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.core.analytics import monte_carlo_simulation
    from dataclasses import asdict

    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades_result = await db.execute(
        select(Trade).where(Trade.backtest_run_id == run_id).order_by(Trade.entry_time)
    )
    trades = trades_result.scalars().all()
    mc_result = monte_carlo_simulation(
        [{"pnl": t.pnl or 0.0, "entry_time": t.entry_time, "exit_time": t.exit_time or t.entry_time} for t in trades],
        run.initial_balance,
    )
    return asdict(mc_result)
