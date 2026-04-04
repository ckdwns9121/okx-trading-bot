import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from app.logging_config import get_logger

logger = get_logger(__name__)

_WS_PUBLIC_LIVE = "wss://ws.okx.com:8443/ws/v5/public"
_WS_PUBLIC_DEMO = "wss://wspap.okx.com:8443/ws/v5/public"

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0


class OKXWebSocket:
    """OKX WebSocket client for real-time candle data."""

    def __init__(
        self,
        on_candle_callback: Callable[[dict[str, Any]], Awaitable[None]],
        mode: str = "demo",
        gap_recovery_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._on_candle = on_candle_callback
        self._gap_recovery = gap_recovery_callback
        self._mode = mode
        self._url = _WS_PUBLIC_DEMO if mode == "demo" else _WS_PUBLIC_LIVE

        self._subscriptions: list[dict[str, str]] = []
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    def subscribe(self, pairs: list[str], timeframe: str) -> None:
        """Register candle channel subscriptions (applied on connect/reconnect)."""
        for pair in pairs:
            channel = f"candle{timeframe}"
            arg = {"channel": channel, "instId": pair}
            if arg not in self._subscriptions:
                self._subscriptions.append(arg)
                logger.info("subscription_registered", channel=channel, pair=pair)

    async def _send_subscriptions(
        self, ws: websockets.WebSocketClientProtocol
    ) -> None:
        if not self._subscriptions:
            return
        msg = {"op": "subscribe", "args": self._subscriptions}
        await ws.send(json.dumps(msg))
        logger.info("subscriptions_sent", count=len(self._subscriptions))

    async def _handle_message(self, raw: str) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("invalid_json", raw=raw[:200])
            return

        # OKX sends {"event": "subscribe"} acks and {"event": "error"} errors
        if "event" in msg:
            event = msg["event"]
            if event == "subscribe":
                logger.info("channel_subscribed", arg=msg.get("arg"))
            elif event == "error":
                logger.error("ws_api_error", code=msg.get("code"), msg=msg.get("msg"))
            return

        # Candle push: {"arg": {"channel": "candle1m", "instId": "BTC-USDT-SWAP"}, "data": [[...]]}
        if "data" not in msg:
            return

        arg: dict[str, str] = msg.get("arg", {})
        channel: str = arg.get("channel", "")
        inst_id: str = arg.get("instId", "")

        if not channel.startswith("candle"):
            return

        for row in msg["data"]:
            # OKX candle row: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
            candle: dict[str, Any] = {
                "timestamp": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "pair": inst_id,
                "confirmed": row[8] == "1" if len(row) > 8 else True,
            }
            try:
                await self._on_candle(candle)
            except Exception as exc:
                logger.exception("candle_callback_error", error=str(exc))

    async def _connect_and_listen(self) -> None:
        logger.info("ws_connecting", url=self._url)
        async with websockets.connect(
            self._url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            await self._send_subscriptions(ws)
            logger.info("ws_connected")

            async for raw in ws:
                if not self._running:
                    break
                await self._handle_message(str(raw))

    async def start(self) -> None:
        """Connect and listen with automatic exponential-backoff reconnection."""
        self._running = True
        backoff = _BACKOFF_INITIAL
        first_connect = True

        while self._running:
            try:
                if not first_connect and self._gap_recovery:
                    logger.info("gap_recovery_triggered")
                    try:
                        await self._gap_recovery()
                    except Exception as exc:
                        logger.error("gap_recovery_error", error=str(exc))

                first_connect = False
                await self._connect_and_listen()

                if self._running:
                    # Clean disconnect — reset backoff and reconnect immediately
                    logger.info("ws_disconnected_cleanly")
                    backoff = _BACKOFF_INITIAL

            except ConnectionClosed as exc:
                if not self._running:
                    break
                logger.warning(
                    "ws_connection_closed",
                    code=exc.rcvd.code if exc.rcvd else None,
                    reason=exc.rcvd.reason if exc.rcvd else "",
                    reconnect_in=backoff,
                )
            except OSError as exc:
                if not self._running:
                    break
                logger.error("ws_os_error", error=str(exc), reconnect_in=backoff)
            except Exception as exc:
                if not self._running:
                    break
                logger.exception("ws_unexpected_error", error=str(exc), reconnect_in=backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

        logger.info("ws_loop_exited")

    async def stop(self) -> None:
        """Gracefully stop the WebSocket client."""
        self._running = False
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
            logger.info("ws_closed")
