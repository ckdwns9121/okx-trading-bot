from __future__ import annotations

import httpx
import pytest

from app.exchange.public_market_data import OKXPublicMarketData


@pytest.mark.asyncio
async def test_get_candles_normalizes_okx_shape_without_auth_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v5/market/candles"
        assert "OK-ACCESS-KEY" not in request.headers
        assert request.url.params["instId"] == "BTC-USDT-SWAP"
        return httpx.Response(
            200,
            json={
                "code": "0",
                "data": [
                    ["1710000000000", "100", "110", "95", "105", "12.5", "0", "0", "1"],
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.okx.com")
    market_data = OKXPublicMarketData(client=client)

    candles = await market_data.get_candles("BTC-USDT-SWAP", "1m", limit=1)

    assert candles == [
        {
            "timestamp": "1710000000000",
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 105.0,
            "volume": 12.5,
            "confirm": "1",
        }
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_candles_falls_back_to_history_endpoint_for_empty_live_page() -> None:
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/api/v5/market/candles":
            return httpx.Response(200, json={"code": "0", "data": []})
        assert request.url.path == "/api/v5/market/history-candles"
        return httpx.Response(
            200,
            json={
                "code": "0",
                "data": [["1709999999000", "10", "11", "9", "10.5", "7", "0", "0", "0"]],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.okx.com")
    market_data = OKXPublicMarketData(client=client)

    candles = await market_data.get_candles("BTC-USDT-SWAP", "1m", limit=1, after="1700000000000")

    assert seen_paths == ["/api/v5/market/candles", "/api/v5/market/history-candles"]
    assert candles[0]["timestamp"] == "1709999999000"
    assert candles[0]["confirm"] == "0"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_ticker_and_top_depth_parse_public_market_data() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v5/market/ticker":
            return httpx.Response(
                200,
                json={
                    "code": "0",
                    "data": [
                        {
                            "instId": "BTC-USDT-SWAP",
                            "last": "100.2",
                            "bidPx": "100.0",
                            "askPx": "100.4",
                            "bidSz": "3",
                            "askSz": "4",
                            "ts": "1710000001000",
                        }
                    ],
                },
            )
        assert request.url.path == "/api/v5/market/books"
        return httpx.Response(
            200,
            json={
                "code": "0",
                "data": [
                    {
                        "ts": "1710000002000",
                        "bids": [["100.0", "2", "0", "1"], ["99.5", "1", "0", "1"]],
                        "asks": [["100.4", "1.5", "0", "1"], ["100.5", "2", "0", "1"]],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.okx.com")
    market_data = OKXPublicMarketData(client=client)

    ticker = await market_data.get_ticker("BTC-USDT-SWAP")
    depth = await market_data.get_order_book_top_depth("BTC-USDT-SWAP", depth=2)

    assert ticker["mid_price"] == pytest.approx(100.2)
    assert ticker["spread_pct"] == pytest.approx(((100.4 - 100.0) / 100.2) * 100.0)
    assert depth["best_bid"] == pytest.approx(100.0)
    assert depth["best_ask"] == pytest.approx(100.4)
    assert depth["bid_depth_notional"] == pytest.approx((100.0 * 2.0) + (99.5 * 1.0))
    assert depth["ask_depth_notional"] == pytest.approx((100.4 * 1.5) + (100.5 * 2.0))
    assert depth["visible_depth"] == pytest.approx(min(depth["bid_depth_notional"], depth["ask_depth_notional"]))
    await client.aclose()
