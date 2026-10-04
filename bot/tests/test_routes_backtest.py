from __future__ import annotations

import math
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import routes_backtest
from app.main import create_app


def _synthetic_candles(count: int, *, start: float = 100.0) -> list[dict[str, Any]]:
    """Deterministic daily series: slow uptrend with a sine wobble, so both
    Donchian and the MA ensemble produce entries and exits."""
    rows: list[dict[str, Any]] = []
    price = start
    day_ms = 86_400_000
    for i in range(count):
        drift = 0.0015
        wobble = 0.02 * math.sin(i / 9.0)
        open_ = price
        close = open_ * (1.0 + drift + wobble)
        high = max(open_, close) * 1.01
        low = min(open_, close) * 0.99
        rows.append(
            {
                "timestamp": str(1_700_000_000_000 + i * day_ms),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "confirm": "1",
            }
        )
        price = close
    return rows


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_fetch(_market: Any, pair: str, *, count: int, bar: str = "1D") -> list[dict[str, Any]]:
        assert bar == "1D"
        return _synthetic_candles(count, start=100.0 if pair.startswith("BTC") else 10.0)

    monkeypatch.setattr(routes_backtest, "fetch_candles", fake_fetch)
    return TestClient(create_app())


def test_donchian_backtest_returns_curve_and_benchmark(client: TestClient) -> None:
    response = client.post("/api/backtest/run", json={"strategy": "donchian", "days": 200})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "donchian_breakout"
    assert body["instruments"] == ["BTC-USDT"]
    assert body["days_tested"] == len(body["equity_curve"]) > 0
    assert "buy_hold_return_pct" in body
    point = body["equity_curve"][0]
    assert set(point) == {"ts", "equity", "buy_hold"}
    assert body["request"]["days"] == 200


def test_ma_backtest_with_two_pairs(client: TestClient) -> None:
    response = client.post(
        "/api/backtest/run",
        json={"strategy": "ma", "pairs": ["btc-usdt", "ETH-USDT", "BTC-USDT"], "days": 300, "ma_periods": [10, 30]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "ma_ensemble"
    assert body["instruments"] == ["BTC-USDT", "ETH-USDT"]  # upper-cased, de-duplicated
    assert body["params"] == {"ma_periods": [10, 30]}
    assert body["starting_equity_usd"] == 2000.0


def test_rejects_swap_pairs(client: TestClient) -> None:
    response = client.post("/api/backtest/run", json={"pairs": ["BTC-USDT-SWAP"]})
    assert response.status_code == 422


def test_rejects_window_shorter_than_warmup(client: TestClient) -> None:
    response = client.post(
        "/api/backtest/run",
        json={"strategy": "donchian", "days": 60, "donchian": {"entry_period": 100, "exit_period": 20}},
    )
    assert response.status_code == 400
    assert "warmup" in response.json()["detail"]


def test_atr_stop_zero_disables_stop(client: TestClient) -> None:
    response = client.post(
        "/api/backtest/run",
        json={"strategy": "donchian", "days": 200, "donchian": {"atr_stop_mult": 0}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["params"]["atr_stop_mult"] is None
