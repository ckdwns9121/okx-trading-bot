from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.core.execution_quality import ExecutionQualityLog
from app.core.risk_gate import KillSwitch, RiskGate, RiskLimits
from scripts import run_trend_following_demo_trader as demo
from tests.test_trend_following_paper_trader import _FakeMarketData, make_candles

SPEC = {"ct_val": Decimal("0.01"), "lot_size": Decimal("0.1"), "min_size": Decimal("0.1")}


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


def base_state() -> dict:
    return {"processed_candle_ts": {}, "trades": [], "positions": {}}


class _FakeOKXClient:
    def __init__(self, *, positions: list[dict] | None = None, fill_price: float = 100.0) -> None:
        self.positions = positions or []
        self.fill_price = fill_price
        self.orders: list[dict] = []

    async def get_positions(self) -> list[dict]:
        return self.positions

    async def place_order(
        self, *, pair, side, size, leverage, order_type, cl_ord_id, pos_side=None, reduce_only=False
    ):
        self.orders.append(
            {
                "pair": pair,
                "side": side,
                "size": size,
                "pos_side": pos_side,
                "reduce_only": reduce_only,
                "cl_ord_id": cl_ord_id,
            }
        )
        return {"code": "0", "data": [{"clOrdId": cl_ord_id, "sCode": "0"}]}

    async def get_order_by_cl_ord_id(self, cl_ord_id, pair=None):
        last = self.orders[-1]
        return {
            "state": "filled",
            "avgPx": str(self.fill_price),
            "accFillSz": last["size"],
            "fee": "-0.05",
        }


def test_contracts_for_notional_rounds_down_to_lot() -> None:
    contracts = demo.contracts_for_notional(
        notional_usd=1000.0,
        price=100.0,
        ct_val=Decimal("0.01"),
        lot_size=Decimal("0.1"),
        min_size=Decimal("0.1"),
    )
    # 1000 / (100 * 0.01) = 1000 raw contracts, lot 0.1 → exactly 1000
    assert contracts == Decimal("1000.0")

    tiny = demo.contracts_for_notional(
        notional_usd=0.01,
        price=100.0,
        ct_val=Decimal("0.01"),
        lot_size=Decimal("0.1"),
        min_size=Decimal("0.1"),
    )
    assert tiny == Decimal("0")


def test_parse_swap_pairs_requires_swap_suffix() -> None:
    assert demo.parse_swap_pairs("btc-usdt-swap") == ("BTC-USDT-SWAP",)
    with pytest.raises(ValueError):
        demo.parse_swap_pairs("BTC-USDT")


@pytest.mark.asyncio
async def test_uptrend_places_demo_buy(tmp_path: Path) -> None:
    candles = make_candles(40)
    price = candles[-1]["close"]
    market = _FakeMarketData(candles, mid_price=price)
    client = _FakeOKXClient(fill_price=price)
    state = base_state()

    trade = await demo.process_pair(
        pair="BTC-USDT-SWAP",
        client=client,
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        spec=SPEC,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        min_trade_usd=50.0,
    )

    assert trade is not None and trade["side"] == "buy"
    assert len(client.orders) == 1
    assert client.orders[0]["reduce_only"] is False
    assert state["positions"]["BTC-USDT-SWAP"]["contracts"] == client.orders[0]["size"]
    assert ExecutionQualityLog(tmp_path / "exec.jsonl").summary()["count"] == 1


@pytest.mark.asyncio
async def test_downtrend_with_position_sells_reduce_only(tmp_path: Path) -> None:
    candles = make_candles(40, start=200.0, step=-1.0)
    price = candles[-1]["close"]
    market = _FakeMarketData(candles, mid_price=price)
    client = _FakeOKXClient(
        positions=[
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "500",
                "posSide": "net",
                "notionalUsd": str(500 * 0.01 * price),
            }
        ],
        fill_price=price,
    )
    state = base_state()
    state["positions"]["BTC-USDT-SWAP"] = {"contracts": "500", "avg_entry_price": 190.0}

    trade = await demo.process_pair(
        pair="BTC-USDT-SWAP",
        client=client,
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        spec=SPEC,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        min_trade_usd=50.0,
    )

    assert trade is not None and trade["side"] == "sell"
    assert client.orders[0]["reduce_only"] is True
    assert Decimal(client.orders[0]["size"]) <= Decimal("500")
    assert trade["realized_pnl_usd"] is not None


@pytest.mark.asyncio
async def test_kill_switch_blocks_demo_entry(tmp_path: Path) -> None:
    candles = make_candles(40)
    market = _FakeMarketData(candles, mid_price=candles[-1]["close"])
    client = _FakeOKXClient()
    gate = make_gate(tmp_path)
    gate.kill_switch.trip(reason="stop", source="test")

    trade = await demo.process_pair(
        pair="BTC-USDT-SWAP",
        client=client,
        market_data=market,
        state=base_state(),
        risk_gate=gate,
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        spec=SPEC,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        min_trade_usd=50.0,
    )
    assert trade is None
    assert client.orders == []


@pytest.mark.asyncio
async def test_reconcile_books_trips_kill_switch_on_mismatch(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    client = _FakeOKXClient(
        positions=[
            {"instId": "DOGE-USDT-SWAP", "pos": "100", "posSide": "net", "notionalUsd": "100"}
        ]
    )
    await demo.reconcile_books(client=client, state=base_state(), risk_gate=gate)
    assert gate.kill_switch.is_tripped()


@pytest.mark.asyncio
async def test_run_refuses_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "OKX_MODE", "live")
    args = demo.build_parser().parse_args(["--once", "--state-file", str(tmp_path / "s.json")])
    with pytest.raises(SystemExit):
        await demo.run(args)


@pytest.mark.asyncio
async def test_donchian_strategy_enters_on_breakout(tmp_path: Path) -> None:
    candles = []
    for index in range(40):
        close = 100.0 + index * 1.0
        candles.append(
            {
                "timestamp": str(index * 86_400_000),
                "open": close - 0.5,
                "high": close + 0.1,
                "low": close - 0.6,
                "close": close,
                "confirm": "1",
            }
        )
    price = candles[-1]["close"]
    market = _FakeMarketData(candles, mid_price=price)
    client = _FakeOKXClient(fill_price=price)
    state = base_state()

    from app.core.donchian import DonchianParams

    trade = await demo.process_pair(
        pair="BTC-USDT-SWAP",
        client=client,
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        spec=SPEC,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        min_trade_usd=50.0,
        strategy="donchian",
        donchian_params=DonchianParams(entry_period=10, exit_period=5, atr_period=10),
    )

    assert trade is not None and trade["side"] == "buy"
    assert trade["target_fraction"] == 1.0
    assert state["donchian_entry"]["BTC-USDT-SWAP"]["atr"] > 0.0


@pytest.mark.asyncio
async def test_donchian_strategy_exits_on_breakdown(tmp_path: Path) -> None:
    candles = []
    for index in range(40):
        close = 200.0 - index * 1.0
        candles.append(
            {
                "timestamp": str(index * 86_400_000),
                "open": close + 0.5,
                "high": close + 0.6,
                "low": close - 0.1,
                "close": close,
                "confirm": "1",
            }
        )
    price = candles[-1]["close"]
    market = _FakeMarketData(candles, mid_price=price)
    client = _FakeOKXClient(
        positions=[
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "500",
                "posSide": "net",
                "notionalUsd": str(500 * 0.01 * price),
            }
        ],
        fill_price=price,
    )
    state = base_state()
    state["positions"]["BTC-USDT-SWAP"] = {"contracts": "500", "avg_entry_price": 190.0}

    from app.core.donchian import DonchianParams

    trade = await demo.process_pair(
        pair="BTC-USDT-SWAP",
        client=client,
        market_data=market,
        state=state,
        risk_gate=make_gate(tmp_path),
        execution_log=ExecutionQualityLog(tmp_path / "exec.jsonl"),
        spec=SPEC,
        ma_periods=(5, 10, 20),
        allocation_usd=1000.0,
        min_trade_usd=50.0,
        strategy="donchian",
        donchian_params=DonchianParams(entry_period=10, exit_period=5, atr_period=10),
    )

    assert trade is not None and trade["side"] == "sell"
    assert trade["target_fraction"] == 0.0
    assert client.orders[0]["reduce_only"] is True
