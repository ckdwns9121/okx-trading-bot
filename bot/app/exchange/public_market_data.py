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
            "raw": dict(row),
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
            "raw": {
                "ts": row.get("ts"),
                "seqId": row.get("seqId"),
                "bids": row.get("bids", [])[: max(1, depth)],
                "asks": row.get("asks", [])[: max(1, depth)],
            },
        }

    async def get_recent_trades(self, pair: str, limit: int = 100) -> list[dict[str, Any]]:
        result = await self._request(
            "/api/v5/market/trades",
            params={"instId": pair, "limit": str(_bounded_limit(limit, maximum=500))},
        )
        return [_normalize_trade(row, pair) for row in result.get("data", [])]

    async def get_trade_history(
        self,
        pair: str,
        *,
        limit: int = 100,
        pagination_type: str = "1",
        after: str | None = None,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "instId": pair,
            "limit": str(_bounded_limit(limit, maximum=100)),
            "type": pagination_type,
        }
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        result = await self._request("/api/v5/market/history-trades", params=params)
        return [_normalize_trade(row, pair) for row in result.get("data", [])]

    async def get_funding_rate(self, pair: str) -> dict[str, Any]:
        result = await self._request("/api/v5/public/funding-rate", params={"instId": pair})
        rows = result.get("data", [])
        if not rows:
            raise RuntimeError(f"OKX funding rate is empty for {pair}")
        return _normalize_funding_rate(rows[0], pair)

    async def get_funding_rate_history(
        self,
        pair: str,
        *,
        limit: int = 100,
        after: str | None = None,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "instId": pair,
            "limit": str(_bounded_limit(limit, maximum=100)),
        }
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        result = await self._request("/api/v5/public/funding-rate-history", params=params)
        return [_normalize_funding_rate(row, pair) for row in result.get("data", [])]

    async def get_open_interest(self, pair: str, *, inst_type: str = "SWAP") -> dict[str, Any]:
        result = await self._request(
            "/api/v5/public/open-interest",
            params={"instType": inst_type, "instId": pair},
        )
        rows = result.get("data", [])
        if not rows:
            raise RuntimeError(f"OKX open interest is empty for {pair}")
        return _normalize_open_interest(rows[0], pair)

    async def get_open_interest_history(
        self,
        pair: str,
        *,
        period: str = "5m",
        limit: int = 100,
        begin: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "instId": pair,
            "period": period,
            "limit": str(_bounded_limit(limit, maximum=100)),
        }
        if begin is not None:
            params["begin"] = begin
        if end is not None:
            params["end"] = end

        result = await self._request("/api/v5/rubik/stat/contracts/open-interest-history", params=params)
        return [_normalize_open_interest_history_row(row, pair) for row in result.get("data", [])]

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


def _normalize_trade(row: Mapping[str, Any], pair: str) -> dict[str, Any]:
    price = _to_float(row.get("px"))
    size = _to_float(row.get("sz"))
    return {
        "instId": row.get("instId", pair),
        "trade_id": str(row.get("tradeId", "")),
        "side": str(row.get("side", "")).lower(),
        "price": price,
        "size": size,
        "notional": price * size,
        "source": row.get("source"),
        "timestamp": _to_int(row.get("ts")),
        "timestamp_iso": _timestamp_iso(row.get("ts")),
        "raw": dict(row),
    }


def _normalize_funding_rate(row: Mapping[str, Any], pair: str) -> dict[str, Any]:
    funding_time = row.get("fundingTime")
    return {
        "instId": row.get("instId", pair),
        "instType": row.get("instType"),
        "funding_rate": _to_float(row.get("fundingRate")),
        "realized_rate": _to_float(row.get("realizedRate")),
        "sett_funding_rate": _to_float(row.get("settFundingRate")),
        "interest_rate": _to_float(row.get("interestRate")),
        "premium": _to_float(row.get("premium")),
        "funding_time": _to_int(funding_time),
        "funding_time_iso": _timestamp_iso(funding_time),
        "next_funding_time": _to_int(row.get("nextFundingTime")),
        "next_funding_time_iso": _timestamp_iso(row.get("nextFundingTime")),
        "prev_funding_time": _to_int(row.get("prevFundingTime")),
        "prev_funding_time_iso": _timestamp_iso(row.get("prevFundingTime")),
        "timestamp": _to_int(row.get("ts")),
        "timestamp_iso": _timestamp_iso(row.get("ts")),
        "method": row.get("method"),
        "sett_state": row.get("settState"),
        "formula_type": row.get("formulaType"),
        "raw": dict(row),
    }


def _normalize_open_interest(row: Mapping[str, Any], pair: str) -> dict[str, Any]:
    return {
        "instId": row.get("instId", pair),
        "instType": row.get("instType"),
        "open_interest": _to_float(row.get("oi")),
        "open_interest_ccy": _to_float(row.get("oiCcy")),
        "open_interest_usd": _to_float(row.get("oiUsd")),
        "timestamp": _to_int(row.get("ts")),
        "timestamp_iso": _timestamp_iso(row.get("ts")),
        "raw": dict(row),
    }


def _normalize_open_interest_history_row(row: list[Any], pair: str) -> dict[str, Any]:
    return {
        "instId": pair,
        "timestamp": _to_int(row[0] if len(row) > 0 else None),
        "timestamp_iso": _timestamp_iso(row[0] if len(row) > 0 else None),
        "open_interest": _to_float(row[1] if len(row) > 1 else None),
        "open_interest_ccy": _to_float(row[2] if len(row) > 2 else None),
        "open_interest_usd": _to_float(row[3] if len(row) > 3 else None),
        "raw": list(row),
    }


def _bounded_limit(limit: int, *, maximum: int) -> int:
    return max(1, min(int(limit), maximum))


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
