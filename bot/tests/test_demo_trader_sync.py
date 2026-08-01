from __future__ import annotations

import pytest

from scripts import run_trend_following_demo_trader as demo
from tests.test_trend_following_demo_trader import _FakeOKXClient


@pytest.mark.asyncio
async def test_startup_sync_adopts_exchange_position() -> None:
    client = _FakeOKXClient(
        positions=[
            {"instId": "ETH-USDT-SWAP", "pos": "1.78", "posSide": "long", "avgPx": "1868.01"}
        ]
    )
    state: dict = {"positions": {}}

    await demo.sync_book_from_exchange(
        client=client, state=state, pairs=("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    )

    assert state["positions"]["ETH-USDT-SWAP"]["contracts"] == "1.78"
    assert state["positions"]["ETH-USDT-SWAP"]["avg_entry_price"] == pytest.approx(1868.01)


@pytest.mark.asyncio
async def test_startup_sync_drops_stale_local_position() -> None:
    client = _FakeOKXClient(positions=[])
    state: dict = {
        "positions": {"BTC-USDT-SWAP": {"contracts": "5", "avg_entry_price": 100.0}}
    }

    await demo.sync_book_from_exchange(client=client, state=state, pairs=("BTC-USDT-SWAP",))

    assert state["positions"] == {}


@pytest.mark.asyncio
async def test_startup_sync_noop_when_books_match() -> None:
    client = _FakeOKXClient(
        positions=[
            {"instId": "ETH-USDT-SWAP", "pos": "1.78", "posSide": "long", "avgPx": "1868.01"}
        ]
    )
    state: dict = {
        "positions": {"ETH-USDT-SWAP": {"contracts": "1.78", "avg_entry_price": 1868.01}}
    }
    await demo.sync_book_from_exchange(client=client, state=state, pairs=("ETH-USDT-SWAP",))
    assert state["positions"]["ETH-USDT-SWAP"]["contracts"] == "1.78"


@pytest.mark.asyncio
async def test_startup_sync_ignores_untracked_instruments() -> None:
    client = _FakeOKXClient(
        positions=[{"instId": "DOGE-USDT-SWAP", "pos": "100", "posSide": "long", "avgPx": "0.1"}]
    )
    state: dict = {"positions": {}}
    await demo.sync_book_from_exchange(client=client, state=state, pairs=("BTC-USDT-SWAP",))
    assert state["positions"] == {}
