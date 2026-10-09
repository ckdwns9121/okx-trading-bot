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
_RETRYABLE_API_CODES = {"50011", "50102"}
_MAX_REQUEST_ATTEMPTS = 3


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


def _safe_json_response(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _is_retryable_okx_response(status_code: int, code: str, body: str) -> bool:
    normalized = body.lower()
    return (
        status_code == 429
        or code in _RETRYABLE_API_CODES
        or "timestamp request expired" in normalized
        or "too many requests" in normalized
    )


def _okx_error_detail(result: dict[str, Any]) -> tuple[str, str]:
    msg = str(result.get("msg", "unknown error"))
    detail_msgs = []
    for item in result.get("data", []):
        if not isinstance(item, dict):
            continue
        s_code = item.get("sCode", "")
        s_msg = item.get("sMsg", "")
        if s_code or s_msg:
            detail_msgs.append(f"[{s_code}] {s_msg}")
    detail = "; ".join(detail_msgs) if detail_msgs else msg
    return msg, detail


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
        max_attempts: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute an authenticated API request with rate limiting.

        ``max_attempts=1`` disables retries. Order placement must use it: a
        timed-out POST may already have been accepted, and resending it would
        double the order. Callers confirm by querying the clOrdId instead.
        """
        import json

        body_str = json.dumps(data) if data else ""
        # Path for signing must include query string
        sign_path = path
        if params:
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            if query:
                sign_path = f"{path}?{query}"

        client = await self._get_client()

        log = logger.bind(method=method, path=path)

        last_response: httpx.Response | None = None
        attempts = max_attempts if max_attempts is not None else _MAX_REQUEST_ATTEMPTS
        for attempt in range(1, attempts + 1):
            await self._rate_limiter.acquire()
            headers = self._build_headers(method, sign_path, body_str)
            try:
                if method.upper() == "GET":
                    response = await client.get(path, params=params, headers=headers)
                else:
                    response = await client.request(
                        method, path, content=body_str, headers=headers
                    )
            except httpx.TransportError as exc:
                log.error("http_transport_error", error=str(exc), attempt=attempt)
                if attempt < attempts:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise

            last_response = response
            result = _safe_json_response(response)
            code = str(result.get("code", "0")) if result is not None else "0"

            if response.status_code != 200:
                if _is_retryable_okx_response(response.status_code, code, response.text):
                    log.warning(
                        "http_retryable_error",
                        status_code=response.status_code,
                        code=code,
                        body=response.text[:500],
                        attempt=attempt,
                    )
                    if attempt < attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                log.error(
                    "http_error",
                    status_code=response.status_code,
                    body=response.text[:500],
                )
                response.raise_for_status()

            if result is None:
                result = response.json()

            code = str(result.get("code", "0"))
            if code != "0":
                msg, detail = _okx_error_detail(result)
                if code in _RETRYABLE_API_CODES:
                    log.warning(
                        "api_retryable_error",
                        code=code,
                        msg=msg,
                        detail=detail,
                        attempt=attempt,
                    )
                    if attempt < attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                log.error("api_error", code=code, msg=msg, detail=detail)
                raise RuntimeError(f"OKX API error {code}: {detail}")

            log.debug("api_request_ok", code=code, attempt=attempt)
            return result

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError(f"OKX request failed after {attempts} attempts: {method} {path}")

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
                    "confirm": row[8] if len(row) > 8 else "1",
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
        reduce_only: bool = False,
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
        if reduce_only:
            data["reduceOnly"] = "true"
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

    async def get_position_mode(self) -> str:
        """Return the account position mode: 'net_mode' or 'long_short_mode'."""
        result = await self._request("GET", "/api/v5/account/config")
        rows = result.get("data", [])
        if not rows:
            raise RuntimeError("OKX account config is empty")
        return str(rows[0].get("posMode") or "net_mode")

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

    async def get_order_by_cl_ord_id(
        self,
        cl_ord_id: str,
        pair: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch an order by client order ID."""
        params: dict[str, Any] = {"clOrdId": cl_ord_id}
        if pair:
            params["instId"] = pair
        result = await self._request(
            "GET",
            "/api/v5/trade/order",
            params=params,
        )
        data: list[dict[str, Any]] = result.get("data", [])
        if not data:
            raise RuntimeError(f"No order found for clOrdId={cl_ord_id!r}")
        return data[0]


    # ------------------------------------------------------------------ #
    # Spot                                                                 #
    # ------------------------------------------------------------------ #

    async def place_spot_market_order(
        self,
        *,
        inst_id: str,
        side: str,
        size: str,
        cl_ord_id: str,
        size_in_quote: bool,
    ) -> dict[str, Any]:
        """Spot market order in cash mode. Sent exactly once (no retries).

        ``size_in_quote=True`` means ``size`` is USDT to spend (market buy);
        otherwise it is the base-currency quantity (market sell).
        """
        data: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": side,
            "ordType": "market",
            "sz": size,
            "clOrdId": cl_ord_id,
            "tgtCcy": "quote_ccy" if size_in_quote else "base_ccy",
        }
        result = await self._request("POST", "/api/v5/trade/order", data=data, max_attempts=1)
        logger.info("spot_order_placed", inst_id=inst_id, side=side, size=size, cl_ord_id=cl_ord_id)
        return result

    async def find_order(self, *, inst_id: str, cl_ord_id: str) -> Optional[dict[str, Any]]:
        """Order by clOrdId, or None when OKX does not know it (never sent / rejected)."""
        try:
            result = await self._request("GET", "/api/v5/trade/order", params={"instId": inst_id, "clOrdId": cl_ord_id})
        except RuntimeError as exc:
            if "51603" in str(exc):  # order does not exist
                return None
            raise
        rows: list[dict[str, Any]] = result.get("data", [])
        return rows[0] if rows else None

    async def get_balances(self) -> dict[str, float]:
        """Total equity per currency (spot holdings + cash), e.g. {"BTC": 1.0, "USDT": 6034.7}."""
        result = await self.get_account_balance()
        row = (result.get("data") or [{}])[0]
        out: dict[str, float] = {}
        for d in row.get("details", []):
            try:
                out[str(d.get("ccy"))] = float(d.get("eq") or d.get("cashBal") or 0.0)
            except (TypeError, ValueError):
                continue
        return out
