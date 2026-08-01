from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.core.execution_quality import ExecutionQualityLog
from app.core.risk_gate import KillSwitch, RiskGate, RiskLimits
from scripts import run_trend_following_paper_trader as paper


def make_candles(count: int, *, start: float = 100.0, step: float = 1.0) -> list[dict]:
    rows = []
    price = start
    for index in range(count):
        rows.append(
            {
                "timestamp": str(1_700_000_000_000 + index * 86_400_000),
                "open": price,
                "high": price + step,
                "low": price - step,
                "close": price + step,
                "volume": 10.0,
                "confirm": "1",
            }
        )
        price += step
    return rows


class _FakeMarketData:
    def __init__(self, candles: list[dict], mid_price: float) -> None:
        self._candles = candles
        self._mid = mid_price

    async def get_candles(self, pair, timeframe, limit=100, after=None, before=None):
        if after is not None:
            return []  # no older history in the fake
        return list(reversed(self._candles[-limit:]))  # OKX returns newest first

    async def get_ticker(self, pair):
        return {"mid_price": self._mid, "last": self._mid}

    async def close(self):
        return None


def make_gate(tmp_path: Path) -> RiskGate:
    return RiskGate(
        limits=RiskLimits(
            max_order_notional_usd=5000.0,
            max_instrument_notional_usd=5000.0,
            max_total_exposure_usd=10000.0,
            max_price_deviation_pct=5.0,
            max_daily_loss_usd=500.0,
            max_orders_per_minute=10,
        ),
        kill_switch=KillSwitch(tmp_path / "kill_switch.json"),
    )


def base_state(allocation: float = 1000.0) -> dict:
    return {
        "book": {"cash_usd": allocation, "positions": {}},
        "processed_candle_ts": {},
        "trades": [],
        "equity_history": [],
    }


def test_parse_pairs_rejects_swap_ids() -> None:
    assert paper.parse_pairs("btc-usdt") == ("BTC-USDT",)
    with pytest.raises(ValueError):
        paper.parse_pairs("BTC-USDT-SWAP")


def test_parse_ma_periods() -> None:
    assert paper.parse_ma_periods("20,50,100") == (20, 50, 100)
    with pytest.raises(ValueError):
        paper.parse_ma_periods("1")


@pytest.mark.asyncio
async def test_uptrend_produces_paper_buy(tmp_path: Path) -> None:
    candles = make_candles(40)
    market = _FakeMarketData(candles, mid_price=candles[-1]["close"])
    state = base_state()

    trade = await paper.process_pair(
        pair="BTC-USDT",
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        fee_pct=0.1,
        min_trade_usd=25.0,
    )

    assert trade is not None and trade["side"] == "buy"
    assert state["book"]["positions"]["BTC-USDT"]["quantity"] > 0
    assert len(state["trades"]) == 1
    # TCA record written
    log = ExecutionQualityLog(tmp_path / "exec.jsonl")
    assert log.summary()["count"] == 1


@pytest.mark.asyncio
async def test_same_candle_is_not_processed_twice(tmp_path: Path) -> None:
    candles = make_candles(40)
    market = _FakeMarketData(candles, mid_price=candles[-1]["close"])
    state = base_state()
    gate = make_gate(tmp_path)
    log = ExecutionQualityLog(tmp_path / "exec.jsonl")

    kwargs = dict(
        pair="BTC-USDT",
        market_data=market,
        state=state,
        risk_gate=gate,
        execution_log=log,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        fee_pct=0.1,
        min_trade_usd=25.0,
    )
    first = await paper.process_pair(**kwargs)
    second = await paper.process_pair(**kwargs)
    assert first is not None
    assert second is None
    assert len(state["trades"]) == 1


@pytest.mark.asyncio
async def test_downtrend_keeps_book_flat(tmp_path: Path) -> None:
    candles = make_candles(40, start=200.0, step=-1.0)
    market = _FakeMarketData(candles, mid_price=candles[-1]["close"])
    state = base_state()

    trade = await paper.process_pair(
        pair="BTC-USDT",
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        fee_pct=0.1,
        min_trade_usd=25.0,
    )
    assert trade is None
    assert state["book"].get("positions", {}) == {}


@pytest.mark.asyncio
async def test_tripped_kill_switch_blocks_paper_entries(tmp_path: Path) -> None:
    candles = make_candles(40)
    market = _FakeMarketData(candles, mid_price=candles[-1]["close"])
    state = base_state()
    gate = make_gate(tmp_path)
    gate.kill_switch.trip(reason="test stop", source="test")

    trade = await paper.process_pair(
        pair="BTC-USDT",
        market_data=market,
        state=state,
        risk_gate=gate,
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        fee_pct=0.1,
        min_trade_usd=25.0,
    )
    assert trade is None
    assert state["trades"] == []


def test_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "paper.json"
    state = paper.load_state(path, pairs=("BTC-USDT",), allocation_usd=1000.0)
    assert state["book"]["cash_usd"] == 1000.0
    paper.save_state(path, state)
    reloaded = paper.load_state(path, pairs=("BTC-USDT",), allocation_usd=1000.0)
    assert reloaded["book"]["cash_usd"] == 1000.0


def test_corrupt_state_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "paper.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(SystemExit):
        paper.load_state(path, pairs=("BTC-USDT",), allocation_usd=1000.0)


@pytest.mark.asyncio
async def test_fetch_daily_candles_orders_ascending_and_confirmed_only() -> None:
    candles = make_candles(30)
    candles[-1]["confirm"] = "0"  # today's partial candle must be excluded
    market = _FakeMarketData(candles, mid_price=100.0)

    rows = await paper.fetch_daily_candles(market, "BTC-USDT", days=25)
    assert len(rows) == 25
    timestamps = [int(row["timestamp"]) for row in rows]
    assert timestamps == sorted(timestamps)
    assert all(row["confirm"] == "1" for row in rows)
