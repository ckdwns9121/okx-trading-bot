from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest

os.environ.setdefault("OKX_API_KEY", "test-key")
os.environ.setdefault("OKX_SECRET", "test-secret")
os.environ.setdefault("OKX_PASSPHRASE", "test-passphrase")

from app.core.signal_research import (
    conservative_probability_size,
    purged_walk_forward_split,
    triple_barrier_label,
)
from app.models.strategy_signal import StrategySignal, StrategySignalOutcome


def test_strategy_signal_models_expose_required_columns() -> None:
    signal_columns = set(StrategySignal.__table__.columns.keys())
    assert {
        "source",
        "strategy_name",
        "pair",
        "timeframe",
        "profile_name",
        "profile_version",
        "evidence_run_id",
        "signal_side",
        "timestamp",
        "features_json",
    }.issubset(signal_columns)

    outcome_columns = set(StrategySignalOutcome.__table__.columns.keys())
    assert {
        "signal_id",
        "label",
        "outcome_pnl",
        "bars_to_exit",
        "exit_reason",
        "max_adverse_excursion",
        "max_favorable_excursion",
    }.issubset(outcome_columns)


def test_triple_barrier_label_prefers_stop_loss_on_same_bar_touch() -> None:
    outcome = triple_barrier_label(
        entry_price=100.0,
        signal_side="long",
        highs=[103.0, 104.0],
        lows=[97.0, 99.0],
        closes=[101.0, 103.0],
        take_profit_pct=2.0,
        stop_loss_pct=2.0,
        max_holding_bars=2,
    )

    assert outcome.label == -1
    assert outcome.outcome_pnl == pytest.approx(-2.0)
    assert outcome.bars_to_exit == 1
    assert outcome.exit_reason == "stop_loss"
    assert outcome.max_adverse_excursion == pytest.approx(3.0)
    assert outcome.max_favorable_excursion == pytest.approx(3.0)


def test_triple_barrier_label_times_out_with_short_pnl() -> None:
    outcome = triple_barrier_label(
        entry_price=100.0,
        signal_side="short",
        highs=[100.5, 101.5, 101.0],
        lows=[99.6, 99.2, 99.4],
        closes=[100.2, 100.8, 99.0],
        take_profit_pct=3.0,
        stop_loss_pct=3.0,
        max_holding_bars=3,
    )

    assert outcome.label == 1
    assert outcome.outcome_pnl == pytest.approx((100.0 / 99.0 - 1.0) * 100.0)
    assert outcome.bars_to_exit == 3
    assert outcome.exit_reason == "time_expiry"
    assert outcome.max_adverse_excursion == pytest.approx(abs((100.0 / 101.5 - 1.0) * 100.0))
    assert outcome.max_favorable_excursion == pytest.approx((100.0 / 99.2 - 1.0) * 100.0)


def test_purged_walk_forward_split_respects_purge_and_embargo() -> None:
    splits = purged_walk_forward_split(
        sample_count=20,
        train_size=8,
        test_size=3,
        purge_size=2,
        embargo_size=2,
    )

    assert len(splits) == 2
    assert splits[0].train_indices == tuple(range(8))
    assert splits[0].test_indices == (10, 11, 12)
    assert splits[1].train_indices == tuple(range(15))
    assert splits[1].test_indices == (17, 18, 19)


def test_conservative_probability_size_uses_step_ladder() -> None:
    assert conservative_probability_size(0.54) == 0.0
    assert conservative_probability_size(0.60) == pytest.approx(0.2)
    assert conservative_probability_size(0.78, max_size=0.5) == pytest.approx(0.35)


def test_strategy_signal_can_capture_append_only_snapshot_shape() -> None:
    signal = StrategySignal(
        source="backtest",
        strategy_name="example_rsi",
        pair="BTC-USDT-SWAP",
        timeframe="5m",
        profile_name="baseline",
        profile_version="v1",
        evidence_run_id="run-123",
        signal_side="long",
        timestamp=datetime(2026, 5, 10, tzinfo=timezone.utc),
        features_json={"score": 0.62, "volatility_regime": "mid"},
    )

    outcome = StrategySignalOutcome(
        label=1,
        outcome_pnl=2.5,
        bars_to_exit=4,
        exit_reason="take_profit",
        max_adverse_excursion=0.8,
        max_favorable_excursion=3.1,
    )
    signal.outcomes.append(outcome)

    assert signal.features_json["score"] == pytest.approx(0.62)
    assert signal.outcomes[0].exit_reason == "take_profit"
