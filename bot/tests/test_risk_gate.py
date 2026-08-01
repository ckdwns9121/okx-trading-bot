from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.risk_gate import (
    AccountState,
    KillSwitch,
    OrderIntent,
    RiskGate,
    RiskLimits,
)


def make_gate(tmp_path: Path, **limit_overrides) -> RiskGate:
    limits = RiskLimits(
        max_order_notional_usd=1000.0,
        max_instrument_notional_usd=2000.0,
        max_total_exposure_usd=4000.0,
        max_price_deviation_pct=1.0,
        max_daily_loss_usd=100.0,
        max_orders_per_minute=3,
        **limit_overrides,
    )
    return RiskGate(limits=limits, kill_switch=KillSwitch(tmp_path / "kill_switch.json"))


def make_intent(**overrides) -> OrderIntent:
    defaults = dict(
        inst_id="BTC-USDT-SWAP",
        side="buy",
        notional_usd=500.0,
        reference_price=100.0,
        execution_price=100.1,
        reduce_only=False,
    )
    defaults.update(overrides)
    return OrderIntent(**defaults)


def test_clean_order_passes_all_checks(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    decision = gate.validate(make_intent(), AccountState())
    assert decision.allowed
    assert decision.rejection_reasons == []


def test_rejects_oversized_order(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    decision = gate.validate(make_intent(notional_usd=1500.0), AccountState())
    assert not decision.allowed
    assert any("max_order_notional" in reason for reason in decision.rejection_reasons)


def test_rejects_price_deviation(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    decision = gate.validate(
        make_intent(reference_price=100.0, execution_price=102.5),
        AccountState(),
    )
    assert not decision.allowed
    assert any("price_deviation" in reason for reason in decision.rejection_reasons)


def test_rejects_when_instrument_limit_would_be_exceeded(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    account = AccountState(
        instrument_notional_usd={"BTC-USDT-SWAP": 1800.0},
        total_exposure_usd=1800.0,
    )
    decision = gate.validate(make_intent(notional_usd=500.0), account)
    assert not decision.allowed
    assert any("instrument_limit" in reason for reason in decision.rejection_reasons)


def test_rejects_when_total_exposure_would_be_exceeded(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    account = AccountState(total_exposure_usd=3800.0)
    decision = gate.validate(make_intent(notional_usd=500.0), account)
    assert not decision.allowed
    assert any("total_exposure" in reason for reason in decision.rejection_reasons)


def test_daily_loss_breach_rejects_and_trips_kill_switch(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    account = AccountState(daily_realized_pnl_usd=-150.0)
    decision = gate.validate(make_intent(), account)
    assert not decision.allowed
    assert gate.kill_switch.is_tripped()
    status = gate.kill_switch.status()
    assert "daily realized loss" in (status["reason"] or "")


def test_kill_switch_blocks_new_entries_but_allows_reduce_only(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    gate.kill_switch.trip(reason="manual stop", source="test")

    blocked = gate.validate(make_intent(), AccountState())
    assert not blocked.allowed

    closing = gate.validate(make_intent(reduce_only=True, side="sell"), AccountState())
    assert closing.allowed


def test_kill_switch_state_survives_new_instance(tmp_path: Path) -> None:
    path = tmp_path / "kill_switch.json"
    KillSwitch(path).trip(reason="incident", source="test")
    assert KillSwitch(path).is_tripped()

    KillSwitch(path).reset(source="operator")
    assert not KillSwitch(path).is_tripped()


def test_corrupt_kill_switch_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "kill_switch.json"
    path.write_text("{not json", encoding="utf-8")
    assert KillSwitch(path).is_tripped()


def test_order_rate_limit(tmp_path: Path) -> None:
    current = {"now": datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)}
    gate = RiskGate(
        limits=RiskLimits(max_orders_per_minute=2),
        kill_switch=KillSwitch(tmp_path / "kill_switch.json"),
        clock=lambda: current["now"],
    )

    assert gate.validate(make_intent(), AccountState()).allowed
    assert gate.validate(make_intent(), AccountState()).allowed
    third = gate.validate(make_intent(), AccountState())
    assert not third.allowed
    assert any("order_rate" in reason for reason in third.rejection_reasons)

    current["now"] += timedelta(seconds=61)
    assert gate.validate(make_intent(), AccountState()).allowed


def test_rejects_nonsense_orders(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    assert not gate.validate(make_intent(notional_usd=0.0), AccountState()).allowed
    assert not gate.validate(make_intent(side="hold"), AccountState()).allowed
    assert not gate.validate(make_intent(execution_price=-1.0), AccountState()).allowed


def test_limits_validation() -> None:
    with pytest.raises(ValueError):
        RiskLimits(max_daily_loss_usd=0.0).validate()
