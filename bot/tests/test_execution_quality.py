from __future__ import annotations

from pathlib import Path

import pytest

from app.core.execution_quality import (
    ExecutionQualityLog,
    ExecutionRecord,
    summarize_execution_records,
)


def test_buy_slippage_positive_when_filled_above_decision() -> None:
    record = ExecutionRecord(
        inst_id="BTC-USDT-SWAP",
        side="buy",
        quantity=1.0,
        decision_price=100.0,
        fill_price=100.5,
    )
    assert record.slippage_pct == pytest.approx(0.5)
    assert record.shortfall_usd == pytest.approx(0.5)


def test_sell_slippage_positive_when_filled_below_decision() -> None:
    record = ExecutionRecord(
        inst_id="BTC-USDT-SWAP",
        side="sell",
        quantity=2.0,
        decision_price=100.0,
        fill_price=99.0,
        fee_usd=0.1,
    )
    assert record.slippage_pct == pytest.approx((100.0 / 99.0 - 1.0) * 100.0)
    assert record.shortfall_usd == pytest.approx(2.0 + 0.1)


def test_price_improvement_is_negative_slippage() -> None:
    record = ExecutionRecord(
        inst_id="ETH-USDT-SWAP",
        side="buy",
        quantity=1.0,
        decision_price=100.0,
        fill_price=99.5,
    )
    assert record.slippage_pct < 0.0
    assert record.shortfall_usd == pytest.approx(-0.5)


def test_record_validation() -> None:
    with pytest.raises(ValueError):
        ExecutionRecord(
            inst_id="X", side="hold", quantity=1.0, decision_price=1.0, fill_price=1.0
        )
    with pytest.raises(ValueError):
        ExecutionRecord(
            inst_id="X", side="buy", quantity=0.0, decision_price=1.0, fill_price=1.0
        )


def test_summary_aggregates_by_instrument() -> None:
    records = [
        ExecutionRecord(
            inst_id="BTC-USDT-SWAP",
            side="buy",
            quantity=1.0,
            decision_price=100.0,
            fill_price=100.2,
            fee_usd=0.05,
        ),
        ExecutionRecord(
            inst_id="ETH-USDT-SWAP",
            side="sell",
            quantity=1.0,
            decision_price=50.0,
            fill_price=50.0,
            fee_usd=0.02,
        ),
    ]
    summary = summarize_execution_records(records)
    assert summary["count"] == 2
    assert summary["total_fees_usd"] == pytest.approx(0.07)
    assert set(summary["by_instrument"]) == {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
    assert summary["worst_slippage_pct"] == pytest.approx(0.2, abs=1e-6)


def test_empty_summary() -> None:
    summary = summarize_execution_records([])
    assert summary["count"] == 0
    assert summary["total_shortfall_usd"] == 0.0


def test_log_roundtrip_and_corrupt_line_tolerance(tmp_path: Path) -> None:
    log = ExecutionQualityLog(tmp_path / "exec.jsonl")
    log.record(
        ExecutionRecord(
            inst_id="BTC-USDT-SWAP",
            side="buy",
            quantity=1.0,
            decision_price=100.0,
            fill_price=100.1,
        )
    )
    log.record(
        ExecutionRecord(
            inst_id="BTC-USDT-SWAP",
            side="sell",
            quantity=1.0,
            decision_price=101.0,
            fill_price=100.9,
        )
    )

    with log.log_path.open("a", encoding="utf-8") as handle:
        handle.write("{broken json\n")

    records = log.load()
    assert len(records) == 2
    assert log.summary()["count"] == 2
    assert log.load(limit=1)[0].side == "sell"


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    log = ExecutionQualityLog(tmp_path / "missing.jsonl")
    assert log.load() == []
    assert log.summary()["count"] == 0
