"""Strategy selector API routes.

GET  /api/selector/regime/{pair}  — detect current market regime
POST /api/selector/recommend      — get strategy recommendation
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["selector"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RegimeOut(BaseModel):
    regime: str
    confidence: float
    adx: float
    volatility: float
    trend_direction: float
    details: dict[str, Any]


class StrategyScoreOut(BaseModel):
    strategy_name: str
    sharpe_ratio: float
    total_pnl: float
    win_rate: float
    regime_fit: float
    composite_score: float


class SelectionResultOut(BaseModel):
    pair: str
    regime: RegimeOut
    recommended_strategy: str
    recommended_params: dict[str, Any]
    scores: list[StrategyScoreOut]
    reasoning: str


class RecommendRequest(BaseModel):
    pair: str = Field(..., description="Instrument ID, e.g. BTC-USDT-SWAP")
    timeframe: str = Field(default="1H", description="Candle timeframe")
    lookback_days: int = Field(default=30, ge=1, le=365, description="Days of history to analyse")
    initial_balance: float = Field(default=10000.0, gt=0)
    leverage: int = Field(default=1, ge=1, le=125)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/selector/regime/{pair:path}",
    response_model=RegimeOut,
    summary="Detect current market regime for a pair",
)
async def detect_regime(
    pair: str,
    request: Request,
    timeframe: str = "1H",
) -> RegimeOut:
    """Fetch recent candles and detect the current market regime."""
    from app.core.regime_detector import MarketRegimeDetector
    from app.exchange.public_market_data import OKXPublicMarketData

    log = logger.bind(pair=pair, timeframe=timeframe)
    log.info("regime_detection_requested")

    market_data = OKXPublicMarketData()

    try:
        raw_candles = await market_data.get_candles(pair=pair, timeframe=timeframe, limit=100)
    finally:
        await market_data.close()

    if not raw_candles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candle data found for {pair}",
        )

    # Sort oldest first (OKX returns newest first)
    raw_candles.sort(key=lambda c: c["timestamp"])

    closes = [c["close"] for c in raw_candles]
    volumes = [c["volume"] for c in raw_candles]
    highs = [c["high"] for c in raw_candles]
    lows = [c["low"] for c in raw_candles]

    detector = MarketRegimeDetector()
    regime = detector.detect(closes=closes, volumes=volumes, highs=highs, lows=lows)

    return RegimeOut(
        regime=regime.regime,
        confidence=regime.confidence,
        adx=regime.adx,
        volatility=regime.volatility,
        trend_direction=regime.trend_direction,
        details=regime.details,
    )


@router.post(
    "/selector/recommend",
    response_model=SelectionResultOut,
    summary="Get strategy recommendation for a pair",
)
async def recommend_strategy(
    body: RecommendRequest,
    request: Request,
) -> SelectionResultOut:
    """Analyse market regime and recommend the best strategy via backtesting."""
    from app.core.strategy_selector import StrategySelector
    from app.db.database import AsyncSessionLocal
    from app.exchange.public_market_data import OKXPublicMarketData

    log = logger.bind(pair=body.pair, timeframe=body.timeframe)
    log.info("strategy_recommendation_requested")

    market_data = OKXPublicMarketData()

    try:
        selector = StrategySelector(
            session_factory=AsyncSessionLocal,
            okx_client=market_data,
        )
        result = await selector.select(
            pair=body.pair,
            timeframe=body.timeframe,
            lookback_days=body.lookback_days,
            initial_balance=body.initial_balance,
            leverage=body.leverage,
        )
    finally:
        await market_data.close()

    return SelectionResultOut(
        pair=result.pair,
        regime=RegimeOut(**result.regime),
        recommended_strategy=result.recommended_strategy,
        recommended_params=result.recommended_params,
        scores=[
            StrategyScoreOut(
                strategy_name=s.strategy_name,
                sharpe_ratio=s.sharpe_ratio,
                total_pnl=s.total_pnl,
                win_rate=s.win_rate,
                regime_fit=s.regime_fit,
                composite_score=s.composite_score,
            )
            for s in result.scores
        ],
        reasoning=result.reasoning,
    )
