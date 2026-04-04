import asyncio
import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://www.okx.com"
_RATE_LIMIT_REQUESTS = 20
_RATE_LIMIT_WINDOW = 2.0  # seconds


class RateLimiter:
    """Token-bucket rate limiter: 20 requests per 2 seconds."""

    def __init__(self, max_requests: int, window: float) -> None:
        self._max_requests = max_requests
        self._window = window
        self._semaphore = asyncio.Semaphore(max_requests)
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Evict timestamps outside the current window
            self._timestamps = [t for t in self._timestamps if now - t < self._window]

            if len(self._timestamps) >= self._max_requests:
                oldest = self._timestamps[0]
                sleep_for = self._window - (now - oldest)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < self._window]

            self._timestamps.append(time.monotonic())


class OKXClient:
    """Async OKX REST API v5 wrapper."""

    def __init__(
        self,
        api_key: str,
        secret: str,
        passphrase: str,
        mode: str = "demo",
    ) -> None:
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._mode = mode
        self._rate_limiter = RateLimiter(_RATE_LIMIT_REQUESTS, _RATE_LIMIT_WINDOW)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=_BASE_URL,
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _sign(self, timestamp: str, method: str, path: str, body: str) -> str:
        """HMAC-SHA256 signature, base64 encoded."""
        prehash = f"{timestamp}{method.upper()}{path}{body}"
        signature = hmac.new(
            self._secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _build_headers(self, method: str, path: str, body: str) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        signature = self._sign(timestamp, method, path, body)
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }
        if self._mode == "demo":
            headers["x-simulated-trading"] = "1"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute an authenticated API request with rate limiting."""
        import json

        await self._rate_limiter.acquire()

        body_str = json.dumps(data) if data else ""
        # Path for signing must include query string
        sign_path = path
        if params:
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            if query:
                sign_path = f"{path}?{query}"

        headers = self._build_headers(method, sign_path, body_str)
        client = await self._get_client()

        log = logger.bind(method=method, path=path)

        try:
            if method.upper() == "GET":
                response = await client.get(path, params=params, headers=headers)
            else:
                response = await client.request(
                    method, path, content=body_str, headers=headers
                )
        except httpx.TransportError as exc:
            log.error("http_transport_error", error=str(exc))
            raise

        if response.status_code != 200:
            log.error(
                "http_error",
                status_code=response.status_code,
                body=response.text[:500],
            )
            response.raise_for_status()

        result: dict[str, Any] = response.json()
        code = result.get("code", "0")
        if code != "0":
            msg = result.get("msg", "unknown error")
            # Extract detailed sub-error from data array
            detail_msgs = []
            for item in result.get("data", []):
                s_code = item.get("sCode", "")
                s_msg = item.get("sMsg", "")
                if s_code or s_msg:
                    detail_msgs.append(f"[{s_code}] {s_msg}")
            detail = "; ".join(detail_msgs) if detail_msgs else msg
            log.error("api_error", code=code, msg=msg, detail=detail)
            raise RuntimeError(f"OKX API error {code}: {detail}")

        log.debug("api_request_ok", code=code)
        return result

    # ------------------------------------------------------------------ #
    # Market data                                                          #
    # ------------------------------------------------------------------ #

    async def get_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch candlestick data.

        Returns list of dicts with keys: timestamp, open, high, low, close, volume.
        OKX returns columns: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        """
        params: dict[str, Any] = {
            "instId": pair,
            "bar": timeframe,
            "limit": str(limit),
        }
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        result = await self._request("GET", "/api/v5/market/candles", params=params)
        # If no data from live endpoint, try history endpoint for older data
        if not result.get("data") and after is not None:
            result = await self._request("GET", "/api/v5/market/history-candles", params=params)
        raw: list[list[str]] = result.get("data", [])

        candles = []
        for row in raw:
            candles.append(
                {
                    "timestamp": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return candles

    async def get_funding_rate(self, pair: str) -> float:
        """Fetch the current funding rate for a SWAP instrument.

        Returns the funding rate as a float (e.g. 0.0001 = 0.01%).
        Returns 0.0 if the rate cannot be fetched.
        """
        try:
            result = await self._request(
                "GET",
                "/api/v5/public/funding-rate",
                params={"instId": pair},
            )
            data = result.get("data", [])
            if data:
                return float(data[0].get("fundingRate", "0"))
        except Exception as exc:
            logger.warning("funding_rate_fetch_error", pair=pair, error=str(exc))
        return 0.0

    # ------------------------------------------------------------------ #
    # Trading                                                              #
    # ------------------------------------------------------------------ #

    async def place_order(
        self,
        pair: str,
        side: str,
        size: str,
        leverage: int = 1,
        order_type: str = "market",
        cl_ord_id: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> dict[str, Any]:
        """Place a futures order.

        For SWAP instruments sz is number of contracts (integer string).
        pos_side: "long" for opening long / closing short, "short" for opening short / closing long.
        When pos_side is None, uses "net" position mode (one-way).
        """
        data: dict[str, Any] = {
            "instId": pair,
            "tdMode": "cross",
            "side": side,
            "ordType": order_type,
            "sz": size,
        }
        if pos_side:
            data["posSide"] = pos_side
        if cl_ord_id is not None:
            data["clOrdId"] = cl_ord_id

        result = await self._request("POST", "/api/v5/trade/order", data=data)
        logger.info("order_placed", pair=pair, side=side, size=size, pos_side=pos_side)
        return result

    async def close_position(self, pair: str, direction: str) -> dict[str, Any]:
        """Close an open position."""
        data: dict[str, Any] = {
            "instId": pair,
            "mgnMode": "cross",
            "posSide": direction,
        }
        result = await self._request("POST", "/api/v5/trade/close-position", data=data)
        logger.info("position_closed", pair=pair, direction=direction)
        return result

    async def set_leverage(
        self,
        pair: str,
        leverage: int,
        margin_mode: str = "cross",
    ) -> dict[str, Any]:
        """Set leverage for a trading pair."""
        data: dict[str, Any] = {
            "instId": pair,
            "lever": str(leverage),
            "mgnMode": margin_mode,
        }
        result = await self._request("POST", "/api/v5/account/set-leverage", data=data)
        logger.info("leverage_set", pair=pair, leverage=leverage, margin_mode=margin_mode)
        return result

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    async def get_account_balance(self) -> dict[str, Any]:
        """Fetch account balance."""
        result = await self._request("GET", "/api/v5/account/balance")
        return result

    async def get_positions(self) -> list[dict[str, Any]]:
        """Fetch open positions."""
        result = await self._request("GET", "/api/v5/account/positions")
        return result.get("data", [])

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """Fetch pending (unfilled) orders."""
        result = await self._request(
            "GET",
            "/api/v5/trade/orders-pending",
            params={"instType": "SWAP"},
        )
        return result.get("data", [])

    async def get_order_by_cl_ord_id(self, cl_ord_id: str) -> dict[str, Any]:
        """Fetch an order by client order ID."""
        result = await self._request(
            "GET",
            "/api/v5/trade/order",
            params={"clOrdId": cl_ord_id},
        )
        data: list[dict[str, Any]] = result.get("data", [])
        if not data:
            raise RuntimeError(f"No order found for clOrdId={cl_ord_id!r}")
        return data[0]
