"""Telegram notification helper for live trading events."""

from __future__ import annotations

from typing import Any

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """Lightweight async Telegram sender.

    Disabled automatically when token/chat_id is missing.
    """

    def __init__(
        self,
        *,
        bot_token: str | None,
        chat_id: str | None,
        enabled: bool = True,
    ) -> None:
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._enabled = enabled and bool(self._bot_token and self._chat_id)
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send_text(self, text: str) -> bool:
        if not self._enabled:
            return False

        try:
            client = await self._get_client()
            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            payload: dict[str, Any] = {
                "chat_id": self._chat_id,
                "text": text[:4096],  # Telegram hard limit
                "disable_web_page_preview": True,
            }
            response = await client.post(url, json=payload)
            ok = response.status_code == 200 and response.json().get("ok") is True
            if not ok:
                logger.warning(
                    "telegram_send_failed",
                    status_code=response.status_code,
                    body=response.text[:300],
                )
            return ok
        except Exception as exc:
            logger.warning("telegram_send_exception", error=str(exc))
            return False
