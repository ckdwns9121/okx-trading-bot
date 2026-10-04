from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings, "PAPER_TREND_STATE_FILE", str(tmp_path / "trend_following_paper.json")
    )
    monkeypatch.setattr(
        settings, "DEMO_TREND_STATE_FILE", str(tmp_path / "trend_following_demo.json")
    )
    return TestClient(create_app())


def test_demo_status_before_first_run(client: TestClient) -> None:
    body = client.get("/api/paper/demo-trader").json()
    assert body["running"] is False
    assert body["status"] == "not_started"


def test_demo_status_recent_loop_is_running(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    state = {
        "strategy": "Donchian Breakout (OKX demo)",
        "config": {"strategy": "donchian", "pairs": ["BTC-USDT-SWAP"], "leverage": 1, "poll_seconds": 3600},
        "processed_candle_ts": {"BTC-USDT-SWAP": "1"},
        "positions": {"BTC-USDT-SWAP": {"contracts": "0.5", "avg_entry_price": 80000.0}, "ETH-USDT-SWAP": {"contracts": "0"}},
        "trades": [
            {"inst_id": "BTC-USDT-SWAP", "side": "buy", "fee_usd": 1.0, "realized_pnl_usd": None},
            {"inst_id": "BTC-USDT-SWAP", "side": "sell", "fee_usd": 1.0, "realized_pnl_usd": 12.5},
        ],
        "last_loop_at": (now - timedelta(minutes=5)).isoformat(),
    }
    Path(settings.DEMO_TREND_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")

    body = client.get("/api/paper/demo-trader").json()
    assert body["running"] is True
    assert body["status"] == "running"
    assert body["pairs"] == ["BTC-USDT-SWAP"]
    assert list(body["positions"]) == ["BTC-USDT-SWAP"]  # zero-contract rows dropped
    assert body["trade_count"] == 2
    assert body["realized_pnl_usd"] == 12.5
    assert body["fees_paid_usd"] == 2.0


def test_demo_status_old_loop_is_stale(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    state = {
        "processed_candle_ts": {"ETH-USDT-SWAP": "1"},
        "trades": [],
        "last_loop_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
    }
    Path(settings.DEMO_TREND_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")

    body = client.get("/api/paper/demo-trader").json()
    assert body["running"] is False
    assert body["status"] == "stale"
    assert body["pairs"] == ["ETH-USDT-SWAP"]  # falls back to processed pairs when config is absent


def test_status_before_first_run(client: TestClient) -> None:
    response = client.get("/api/paper/trend-following")
    assert response.status_code == 200
    assert response.json()["running"] is False


def test_status_with_state_file(client: TestClient) -> None:
    state = {
        "strategy": "Daily MA Trend Following (paper)",
        "book": {"cash_usd": 900.0, "positions": {"BTC-USDT": {"quantity": 0.001}}},
        "trades": [{"inst_id": "BTC-USDT", "side": "buy"}],
        "equity_history": [{"at": "2026-08-02T00:00:00+00:00", "equity_usd": 1000.0}],
    }
    Path(settings.PAPER_TREND_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")

    body = client.get("/api/paper/trend-following").json()
    assert body["running"] is True
    assert body["trade_count"] == 1
    assert body["book"]["cash_usd"] == 900.0
