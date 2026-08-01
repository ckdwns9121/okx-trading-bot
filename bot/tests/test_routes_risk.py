from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.execution_quality import ExecutionQualityLog, ExecutionRecord
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "RISK_KILL_SWITCH_FILE", str(tmp_path / "kill_switch.json"))
    monkeypatch.setattr(settings, "RISK_EXECUTION_LOG_FILE", str(tmp_path / "exec.jsonl"))
    return TestClient(create_app())


def test_risk_status_reports_limits_and_untripped_switch(client: TestClient) -> None:
    response = client.get("/api/risk/status")
    assert response.status_code == 200
    body = response.json()
    assert body["kill_switch"]["tripped"] is False
    assert body["limits"]["max_daily_loss_usd"] > 0


def test_trip_and_reset_kill_switch(client: TestClient) -> None:
    tripped = client.post("/api/risk/kill-switch/trip", json={"reason": "manual emergency stop"})
    assert tripped.status_code == 200
    assert tripped.json()["tripped"] is True

    status = client.get("/api/risk/status").json()
    assert status["kill_switch"]["tripped"] is True
    assert status["kill_switch"]["reason"] == "manual emergency stop"

    reset = client.post("/api/risk/kill-switch/reset")
    assert reset.status_code == 200
    assert reset.json()["tripped"] is False


def test_trip_requires_reason(client: TestClient) -> None:
    response = client.post("/api/risk/kill-switch/trip", json={"reason": ""})
    assert response.status_code == 422


def test_execution_quality_summary(client: TestClient) -> None:
    log = ExecutionQualityLog(settings.RISK_EXECUTION_LOG_FILE)
    log.record(
        ExecutionRecord(
            inst_id="BTC-USDT-SWAP",
            side="buy",
            quantity=1.0,
            decision_price=100.0,
            fill_price=100.3,
            fee_usd=0.05,
        )
    )

    response = client.get("/api/risk/execution-quality")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["avg_slippage_pct"] == pytest.approx(0.3, abs=1e-6)


def test_reconciliation_returns_503_without_okx_client(client: TestClient) -> None:
    response = client.get("/api/risk/reconciliation")
    assert response.status_code == 503
