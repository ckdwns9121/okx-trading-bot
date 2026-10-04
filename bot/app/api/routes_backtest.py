"""Backtest API — runs the pure strategy backtests on fresh OKX daily candles.

Read-only by construction: fetches public candles, places no orders, writes no
state. The strategy math lives in ``app.core`` (look-ahead-free, fee-aware);
this module only validates the request, fetches data, and shapes the response
so the desktop/dashboard can show an equity curve next to buy-and-hold.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.core.donchian import DonchianParams, backtest_donchian
from app.core.trend_following import backtest_trend_following
from app.exchange.public_market_data import OKXPublicMarketData
from scripts.run_trend_following_paper_trader import fetch_candles

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

MIN_DAYS = 60
MAX_DAYS = 1500
MAX_PAIRS = 6


class DonchianRequest(BaseModel):
    entry_period: int = Field(55, ge=5, le=400)
    exit_period: int = Field(20, ge=2, le=400)
    atr_period: int = Field(20, ge=2, le=200)
    atr_stop_mult: float = Field(2.0, ge=0.0, le=20.0, description="0 disables the ATR stop")

    def to_params(self) -> DonchianParams:
        return DonchianParams(
            entry_period=self.entry_period,
            exit_period=self.exit_period,
            atr_period=self.atr_period,
            atr_stop_mult=self.atr_stop_mult if self.atr_stop_mult > 0 else None,
        )


class BacktestRequest(BaseModel):
    strategy: Literal["donchian", "ma"] = "donchian"
    pairs: list[str] = Field(default_factory=lambda: ["BTC-USDT"], min_length=1, max_length=MAX_PAIRS)
    days: int = Field(400, ge=MIN_DAYS, le=MAX_DAYS)
    allocation_usd: float = Field(1000.0, gt=0.0, le=10_000_000.0)
    fee_pct: float = Field(0.10, ge=0.0, le=5.0, description="Taker fee per side, percent")
    min_trade_usd: float = Field(25.0, ge=0.0)
    donchian: DonchianRequest = Field(default_factory=DonchianRequest)
    ma_periods: list[int] = Field(default_factory=lambda: [20, 50, 100], min_length=1, max_length=6)

    @field_validator("pairs")
    @classmethod
    def _spot_pairs(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            pair = raw.strip().upper()
            if not pair:
                continue
            if pair.endswith("-SWAP"):
                raise ValueError(f"{pair}: backtests run on spot pairs (e.g. BTC-USDT)")
            if "-" not in pair:
                raise ValueError(f"{pair}: expected BASE-QUOTE, e.g. BTC-USDT")
            if pair not in cleaned:
                cleaned.append(pair)
        if not cleaned:
            raise ValueError("at least one pair is required")
        return cleaned

    @field_validator("ma_periods")
    @classmethod
    def _ma_periods(cls, value: list[int]) -> list[int]:
        periods = sorted({int(p) for p in value})
        if any(p <= 1 for p in periods):
            raise ValueError("ma periods must be greater than 1")
        return periods

    def warmup(self) -> int:
        if self.strategy == "donchian":
            return self.donchian.to_params().warmup()
        return max(self.ma_periods)


@router.post("/run", summary="Run a cost-aware daily backtest on live OKX candles")
async def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    warmup = req.warmup()
    if req.days <= warmup + 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"days must exceed the warmup period ({warmup + 1}) for these parameters",
        )

    market = OKXPublicMarketData()
    candles: dict[str, list[dict[str, Any]]] = {}
    try:
        for pair in req.pairs:
            rows = await fetch_candles(market, pair, count=req.days, bar="1D")
            if len(rows) <= warmup + 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{pair}: OKX returned {len(rows)} daily candles; need more than {warmup + 1}",
                )
            candles[pair] = rows
    except HTTPException:
        raise
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"candle fetch failed: {exc}") from exc
    finally:
        await market.close()

    common = {
        "allocation_usd_per_inst": req.allocation_usd,
        "fee_pct_per_side": req.fee_pct,
        "min_trade_usd": req.min_trade_usd,
    }
    try:
        if req.strategy == "donchian":
            result = backtest_donchian(candles, params=req.donchian.to_params(), **common)
        else:
            result = backtest_trend_following(candles, ma_periods=req.ma_periods, **common)
            result["strategy"] = "ma_ensemble"
            result["params"] = {"ma_periods": req.ma_periods}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Buy-and-hold benchmark for Donchian too, so both strategies compare alike.
    if "buy_hold_return_pct" not in result:
        _attach_buy_hold(result, candles, warmup=warmup, allocation_usd=req.allocation_usd, fee_pct=req.fee_pct)

    first_rows = next(iter(candles.values()))
    result["request"] = req.model_dump()
    result["candles_from"] = str(first_rows[0].get("timestamp"))
    result["candles_to"] = str(first_rows[-1].get("timestamp"))
    return result


def _attach_buy_hold(
    result: dict[str, Any],
    candles: dict[str, list[dict[str, Any]]],
    *,
    warmup: int,
    allocation_usd: float,
    fee_pct: float,
) -> None:
    """Equal-weight buy at the first fill bar, hold to the end — same fee model as the strategies."""

    length = min(len(rows) for rows in candles.values())
    quantities: dict[str, float] = {}
    for inst_id, rows in candles.items():
        entry_price = float(rows[warmup + 1]["open"])
        fee = allocation_usd * fee_pct / 100.0
        quantities[inst_id] = (allocation_usd - fee) / entry_price

    curve: list[float] = []
    for index in range(warmup, length - 1):
        curve.append(
            sum(quantities[inst_id] * float(rows[index + 1]["close"]) for inst_id, rows in candles.items())
        )
    starting = allocation_usd * len(candles)
    peak = starting
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100.0)

    result["buy_hold_return_pct"] = ((curve[-1] / starting) - 1.0) * 100.0 if curve else 0.0
    result["buy_hold_max_drawdown_pct"] = max_dd
    for point, bh in zip(result.get("equity_curve", []), curve):
        point["buy_hold"] = round(bh, 2)
