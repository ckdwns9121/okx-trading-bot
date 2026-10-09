from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "DONCHIAN_STATE_FILE", str(tmp_path / "s.json"))
    return TestClient(create_app())


def test_not_started(client: TestClient) -> None:
    assert client.get("/api/trader/donchian").json() == {"status": "not_started"}


def test_running_with_trades(client: TestClient) -> None:
    Path(settings.DONCHIAN_STATE_FILE).write_text(json.dumps({
        "strategy": "x", "config": {"poll_seconds": 600, "capital_usd": 4000},
        "last_loop_at": datetime.now(timezone.utc).isoformat(),
        "sleeves": {"BTC-USDT": {"inst": "BTC-USDT", "cash_usd": 500, "qty": 0.01}},
        "trades": [{"realized_pnl_usd": None, "fee_usd": 1.0}, {"realized_pnl_usd": 12.5, "fee_usd": 1.0}],
        "pending": {}, "handled_bar": {},
    }))
    body = client.get("/api/trader/donchian").json()
    assert body["status"] == "running"
    assert body["trade_count"] == 2 and body["realized_pnl_usd"] == 12.5 and body["fees_usd"] == 2.0
