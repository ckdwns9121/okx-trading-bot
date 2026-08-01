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
    return TestClient(create_app())


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
