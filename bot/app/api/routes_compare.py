"""Strategy comparison API routes.

POST /api/compare              — run backtests for multiple strategies on multiple pairs
GET  /api/compare/strategies   — list all strategy names with descriptions
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["compare"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    strategies: list[str] = Field(..., min_length=1, description="Strategy names to compare")
    pairs: list[str] = Field(..., min_length=1, description="Instrument IDs")
    timeframe: str = Field(..., description="Candle timeframe, e.g. 4H")
    start_date: str = Field(..., description="ISO-8601 start date")
    end_date: str = Field(..., description="ISO-8601 end date")
    initial_balance: float = Field(default=10000.0, gt=0)
    leverage: int = Field(default=1, ge=1, le=125)

    @field_validator("start_date", "end_date")
    @classmethod
    def _parse_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 date: {v!r}") from exc
        return v


class CompareResultOut(BaseModel):
    strategy: str
    pair: str
    total_pnl: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    profit_factor: float


class StrategyInfoOut(BaseModel):
    name: str
    description: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_description(strategy_cls: type) -> str:
    """Extract the first line of a strategy class docstring."""
    doc = getattr(strategy_cls, "__doc__", None) or ""
    first_line = doc.strip().split("\n")[0].strip().rstrip(".")
    return first_line if first_line else strategy_cls.__name__


def _compute_profit_factor(trades: list) -> float:
    """sum(winning_pnl) / abs(sum(losing_pnl)), or 0.0 if no losers."""
    winning = sum(t.pnl for t in trades if t.pnl > 0)
    losing = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if losing == 0:
        return float(winning) if winning > 0 else 0.0
    return winning / losing


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/compare",
    response_model=list[CompareResultOut],
    summary="Run backtests for multiple strategies on multiple pairs",
)
async def run_comparison(
    body: CompareRequest,
    request: Request,
) -> list[CompareResultOut]:
    """Execute backtests for every strategy x pair combination and return comparison metrics."""
    from app.config import settings
    from app.core.backtest_engine import BacktestEngine
    from app.core.strategy_registry import registry
    from app.db.database import AsyncSessionLocal
    from app.exchange.data_collector import DataCollector
    from app.exchange.okx_client import OKXClient

    # Validate all strategies exist
    available = registry.list_all()
    for name in body.strategies:
        if name not in available:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown strategy {name!r}. Available: {available}",
            )

    start_dt = datetime.fromisoformat(body.start_date).replace(tzinfo=None)
    end_dt = datetime.fromisoformat(body.end_date).replace(tzinfo=None)

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be after start_date",
        )

    log = logger.bind(
        strategies=body.strategies,
        pairs=body.pairs,
        timeframe=body.timeframe,
    )
    log.info("comparison_started")

    results: list[CompareResultOut] = []

    # Fetch candles for each pair ONCE, then run all strategies against cached data
    for pair in body.pairs:
        log_pair = log.bind(pair=pair)

        # Fetch and persist candles for this pair
        okx_client = OKXClient(
            api_key=settings.OKX_API_KEY,
            secret=settings.OKX_SECRET,
            passphrase=settings.OKX_PASSPHRASE,
            mode=settings.OKX_MODE,
        )
        async with AsyncSessionLocal() as session:
            try:
                collector = DataCollector(okx_client=okx_client, db_session=session)
                candle_count = await collector.fetch_historical_candles(
                    pair=pair,
                    timeframe=body.timeframe,
                    start_date=start_dt,
                    end_date=end_dt,
                )
                await session.commit()
                log_pair.info("candles_fetched", count=candle_count)
            finally:
                await okx_client.close()

        # Run each strategy against the cached candles
        for strategy_name in body.strategies:
            log_strat = log_pair.bind(strategy=strategy_name)
            log_strat.info("comparison_backtest_start")

            try:
                async with AsyncSessionLocal() as session:
                    strategy_cls = registry.get(strategy_name)
                    strategy_inst = strategy_cls()
                    strategy_inst.configure({})

                    engine = BacktestEngine(db_session=session)
                    bt_result = await engine.run(
                        strategy=strategy_inst,
                        pair=pair,
                        timeframe=body.timeframe,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_balance=body.initial_balance,
                        leverage=body.leverage,
                    )
                    await session.commit()

                profit_factor = _compute_profit_factor(bt_result.trades)

                results.append(
                    CompareResultOut(
                        strategy=strategy_name,
                        pair=pair,
                        total_pnl=round(bt_result.total_pnl, 2),
                        win_rate=round(bt_result.win_rate, 4),
                        max_drawdown=round(bt_result.max_drawdown, 4),
                        sharpe_ratio=round(bt_result.sharpe_ratio, 4),
                        trade_count=bt_result.trade_count,
                        profit_factor=round(profit_factor, 4),
                    )
                )
                log_strat.info(
                    "comparison_backtest_complete",
                    pnl=bt_result.total_pnl,
                    trades=bt_result.trade_count,
                )

            except Exception as exc:
                log_strat.error("comparison_backtest_failed", error=str(exc), exc_info=True)
                results.append(
                    CompareResultOut(
                        strategy=strategy_name,
                        pair=pair,
                        total_pnl=0.0,
                        win_rate=0.0,
                        max_drawdown=0.0,
                        sharpe_ratio=0.0,
                        trade_count=0,
                        profit_factor=0.0,
                    )
                )

    log.info("comparison_complete", total_results=len(results))
    return results


@router.get(
    "/compare/strategies",
    response_model=list[StrategyInfoOut],
    summary="List all strategies with descriptions",
)
async def list_strategy_infos(request: Request) -> list[StrategyInfoOut]:
    """Return all registered strategy names with their docstring descriptions."""
    from app.core.strategy_registry import registry

    infos: list[StrategyInfoOut] = []
    for name in registry.list_all():
        cls = registry.get(name)
        infos.append(
            StrategyInfoOut(
                name=name,
                description=_extract_description(cls),
            )
        )
    return infos
