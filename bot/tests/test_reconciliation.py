from __future__ import annotations

from pathlib import Path

import pytest

from app.core.reconciliation import reconcile_positions, run_reconciliation
from app.core.risk_gate import KillSwitch


def okx_row(inst_id: str, pos: str, pos_side: str = "net", avg_px: str = "100") -> dict:
    return {"instId": inst_id, "pos": pos, "posSide": pos_side, "avgPx": avg_px}


def test_matching_books_produce_clean_report() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "long", "quantity": 2.0}],
        [okx_row("BTC-USDT-SWAP", "2")],
    )
    assert report.ok
    assert not report.critical


def test_detects_position_missing_on_exchange() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "long", "quantity": 2.0}],
        [],
    )
    assert not report.ok
    assert report.critical
    assert report.discrepancies[0].kind == "missing_on_exchange"


def test_detects_unexpected_exchange_position() -> None:
    report = reconcile_positions([], [okx_row("ETH-USDT-SWAP", "5")])
    assert report.critical
    assert report.discrepancies[0].kind == "unexpected_on_exchange"


def test_detects_size_mismatch_beyond_tolerance() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "long", "quantity": 10.0}],
        [okx_row("BTC-USDT-SWAP", "9")],
        size_tolerance_pct=0.5,
    )
    assert report.critical
    assert report.discrepancies[0].kind == "size_mismatch"


def test_size_within_tolerance_is_ok() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "long", "quantity": 1000.0}],
        [okx_row("BTC-USDT-SWAP", "999")],
        size_tolerance_pct=0.5,
    )
    assert report.ok


def test_detects_direction_mismatch_with_net_mode_sign() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "long", "quantity": 2.0}],
        [okx_row("BTC-USDT-SWAP", "-2")],
    )
    assert report.critical
    assert report.discrepancies[0].kind == "direction_mismatch"


def test_long_short_pos_side_mode_is_normalized() -> None:
    report = reconcile_positions(
        [{"inst_id": "BTC-USDT-SWAP", "direction": "short", "quantity": 3.0}],
        [okx_row("BTC-USDT-SWAP", "3", pos_side="short")],
    )
    assert report.ok


def test_zero_size_exchange_rows_are_ignored() -> None:
    report = reconcile_positions([], [okx_row("BTC-USDT-SWAP", "0")])
    assert report.ok
    assert report.exchange_position_count == 0


class _FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def get_positions(self) -> list[dict]:
        return self._rows


class _FakeSession:
    def __init__(self) -> None:
        self.executed = False

    async def execute(self, _query):
        self.executed = True

        class _Result:
            def scalars(self):
                return self

            def all(self):
                return []

        return _Result()


@pytest.mark.asyncio
async def test_run_reconciliation_trips_kill_switch_on_critical(tmp_path: Path) -> None:
    kill_switch = KillSwitch(tmp_path / "kill_switch.json")
    report = await run_reconciliation(
        okx_client=_FakeClient([okx_row("DOGE-USDT-SWAP", "100")]),
        session=_FakeSession(),
        kill_switch=kill_switch,
        trip_on_critical=True,
    )
    assert report.critical
    assert kill_switch.is_tripped()
    assert "reconciliation" in (kill_switch.status()["reason"] or "")


@pytest.mark.asyncio
async def test_run_reconciliation_without_trip_leaves_switch_alone(tmp_path: Path) -> None:
    kill_switch = KillSwitch(tmp_path / "kill_switch.json")
    report = await run_reconciliation(
        okx_client=_FakeClient([]),
        session=_FakeSession(),
        kill_switch=kill_switch,
        trip_on_critical=True,
    )
    assert report.ok
    assert not kill_switch.is_tripped()
