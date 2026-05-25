from __future__ import annotations

import httpx
import pytest

from app.exchange.okx_client import OKXClient


class _FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.get_calls = 0
        self.request_calls = 0

    async def get(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.get_calls += 1
        return self.responses.pop(0)

    async def request(
        self,
        method: str,
        path: str,
        *,
        content: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.request_calls += 1
        return self.responses.pop(0)


def _response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://www.okx.com/api/v5/account/positions"),
    )


@pytest.mark.asyncio
async def test_request_retries_timestamp_expired_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncClient(
        [
            _response(401, {"code": "50102", "msg": "Timestamp request expired", "data": []}),
            _response(200, {"code": "0", "data": [{"instId": "GRASS-USDT-SWAP"}]}),
        ]
    )
    client = OKXClient("key", "secret", "passphrase", mode="demo")

    async def fake_get_client() -> _FakeAsyncClient:
        return fake

    monkeypatch.setattr(client, "_get_client", fake_get_client)

    result = await client._request("GET", "/api/v5/account/positions")

    assert result["code"] == "0"
    assert fake.get_calls == 2
