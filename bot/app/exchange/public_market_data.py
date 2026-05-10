from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://www.okx.com"


class OKXPublicMarketData:
    """Read-only OKX public market-data adapter."""

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout or httpx.Timeout(10.0, connect=5.0)
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("okx_public_market_data_http_error", path=path, error=str(exc))
            raise

        payload: dict[str, Any] = response.json()
        code = str(payload.get("code", "0"))
        if code != "0":
            msg = payload.get("msg", "unknown error")
            logger.error("okx_public_market_data_api_error", path=path, code=code, msg=msg)
            raise RuntimeError(f"OKX public API error {code}: {msg}")
        return payload

    async def get_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100,
        after: str | None = None,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "instId": pair,
            "bar": timeframe,
            "limit": str(limit),
        }
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        result = await self._request("/api/v5/market/candles", params=params)
        if not result.get("data") and after is not None:
            result = await self._request("/api/v5/market/history-candles", params=params)

        return [self._normalize_candle(row) for row in result.get("data", [])]

    async def get_ticker(self, pair: str) -> dict[str, Any]:
        result = await self._request("/api/v5/market/ticker", params={"instId": pair})
        rows = result.get("data", [])
        if not rows:
            raise RuntimeError(f"OKX ticker is empty for {pair}")

        row = rows[0]
        bid = _to_float(row.get("bidPx"))
        ask = _to_float(row.get("askPx"))
        last = _to_float(row.get("last"))
        mid = _midpoint(bid, ask) if bid > 0 and ask > 0 else last
        return {
            "instId": row.get("instId", pair),
            "last": last,
            "bid": bid,
            "ask": ask,
            "bid_size": _to_float(row.get("bidSz")),
            "ask_size": _to_float(row.get("askSz")),
            "mid_price": mid,
            "spread_pct": _spread_pct(bid, ask),
            "timestamp": _to_int(row.get("ts")),
            "timestamp_iso": _timestamp_iso(row.get("ts")),
        }

    async def get_order_book_top_depth(self, pair: str, depth: int = 5) -> dict[str, Any]:
        result = await self._request(
            "/api/v5/market/books",
            params={"instId": pair, "sz": str(max(1, depth))},
        )
        rows = result.get("data", [])
        if not rows:
            raise RuntimeError(f"OKX order book is empty for {pair}")

        row = rows[0]
        bids = [_normalize_book_level(level) for level in row.get("bids", [])]
        asks = [_normalize_book_level(level) for level in row.get("asks", [])]
        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 0.0
        bid_depth_notional = sum(level["price"] * level["size"] for level in bids)
        ask_depth_notional = sum(level["price"] * level["size"] for level in asks)
        return {
            "instId": pair,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_size": bids[0]["size"] if bids else 0.0,
            "best_ask_size": asks[0]["size"] if asks else 0.0,
            "bid_depth_notional": bid_depth_notional,
            "ask_depth_notional": ask_depth_notional,
            "visible_depth": min(bid_depth_notional, ask_depth_notional),
            "mid_price": _midpoint(best_bid, best_ask),
            "spread_pct": _spread_pct(best_bid, best_ask),
            "timestamp": _to_int(row.get("ts")),
            "timestamp_iso": _timestamp_iso(row.get("ts")),
            "bids": bids,
            "asks": asks,
        }

    @staticmethod
    def _normalize_candle(row: list[str]) -> dict[str, Any]:
        return {
            "timestamp": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "confirm": row[8] if len(row) > 8 else "1",
        }


def _normalize_book_level(level: list[str]) -> dict[str, float]:
    return {
        "price": float(level[0]),
        "size": float(level[1]),
    }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _timestamp_iso(value: Any) -> str | None:
    ts = _to_int(value)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()


def _midpoint(bid: float, ask: float) -> float:
    if bid <= 0 or ask <= 0:
        return 0.0
    return (bid + ask) / 2.0


def _spread_pct(bid: float, ask: float) -> float:
    mid = _midpoint(bid, ask)
    if mid <= 0:
        return 0.0
    return ((ask - bid) / mid) * 100.0
