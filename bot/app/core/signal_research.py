from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TripleBarrierOutcome:
    label: int
    outcome_pnl: float
    bars_to_exit: int
    exit_reason: str
    max_adverse_excursion: float
    max_favorable_excursion: float


@dataclass(frozen=True)
class WalkForwardSplit:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


def _validate_signal_side(signal_side: str) -> str:
    normalized = signal_side.lower()
    if normalized not in {"long", "short"}:
        raise ValueError("signal_side must be 'long' or 'short'")
    return normalized


def _return_pct(entry_price: float, observed_price: float, signal_side: str) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if signal_side == "long":
        return ((observed_price / entry_price) - 1.0) * 100.0
    return ((entry_price / observed_price) - 1.0) * 100.0


def triple_barrier_label(
    *,
    entry_price: float,
    signal_side: str,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    take_profit_pct: float,
    stop_loss_pct: float,
    max_holding_bars: int,
) -> TripleBarrierOutcome:
    """Deterministically label one signal with a conservative triple barrier.

    All percentage outputs are signed percentage returns, not fractions.
    If both barriers are touched within the same bar, the stop-loss wins to
    avoid optimistic labels.
    """

    side = _validate_signal_side(signal_side)
    if len(highs) != len(lows) or len(highs) != len(closes):
        raise ValueError("highs, lows, and closes must have the same length")
    if max_holding_bars <= 0:
        raise ValueError("max_holding_bars must be positive")
    if take_profit_pct <= 0 or stop_loss_pct <= 0:
        raise ValueError("take_profit_pct and stop_loss_pct must be positive")
    if len(closes) < max_holding_bars:
        raise ValueError("not enough bars for requested max_holding_bars")

    max_adverse_excursion = 0.0
    max_favorable_excursion = 0.0

    for offset in range(max_holding_bars):
        high = highs[offset]
        low = lows[offset]
        favorable_price = high if side == "long" else low
        adverse_price = low if side == "long" else high

        favorable_excursion = _return_pct(entry_price, favorable_price, side)
        adverse_excursion = _return_pct(entry_price, adverse_price, side)
        max_favorable_excursion = max(max_favorable_excursion, favorable_excursion)
        max_adverse_excursion = min(max_adverse_excursion, adverse_excursion)

        hit_take_profit = favorable_excursion >= take_profit_pct
        hit_stop_loss = adverse_excursion <= -stop_loss_pct

        if hit_stop_loss:
            return TripleBarrierOutcome(
                label=-1,
                outcome_pnl=-stop_loss_pct,
                bars_to_exit=offset + 1,
                exit_reason="stop_loss",
                max_adverse_excursion=abs(max_adverse_excursion),
                max_favorable_excursion=max_favorable_excursion,
            )
        if hit_take_profit:
            return TripleBarrierOutcome(
                label=1,
                outcome_pnl=take_profit_pct,
                bars_to_exit=offset + 1,
                exit_reason="take_profit",
                max_adverse_excursion=abs(max_adverse_excursion),
                max_favorable_excursion=max_favorable_excursion,
            )

    terminal_pnl = _return_pct(entry_price, closes[max_holding_bars - 1], side)
    if terminal_pnl > 0:
        label = 1
    elif terminal_pnl < 0:
        label = -1
    else:
        label = 0

    return TripleBarrierOutcome(
        label=label,
        outcome_pnl=terminal_pnl,
        bars_to_exit=max_holding_bars,
        exit_reason="time_expiry",
        max_adverse_excursion=abs(max_adverse_excursion),
        max_favorable_excursion=max_favorable_excursion,
    )


def purged_walk_forward_split(
    *,
    sample_count: int,
    train_size: int,
    test_size: int,
    purge_size: int = 0,
    embargo_size: int = 0,
    step_size: int | None = None,
) -> list[WalkForwardSplit]:
    """Build expanding walk-forward splits with purge and embargo gaps."""

    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size and test_size must be positive")
    if purge_size < 0 or embargo_size < 0:
        raise ValueError("purge_size and embargo_size must be non-negative")

    effective_step = test_size if step_size is None else step_size
    if effective_step <= 0:
        raise ValueError("step_size must be positive")

    splits: list[WalkForwardSplit] = []
    train_end = train_size

    while True:
        test_start = train_end + purge_size
        test_end = test_start + test_size
        if test_end > sample_count:
            break

        splits.append(
            WalkForwardSplit(
                train_indices=tuple(range(train_end)),
                test_indices=tuple(range(test_start, test_end)),
            )
        )

        next_train_end = max(train_end + effective_step, test_end + embargo_size)
        if next_train_end == train_end:
            break
        train_end = next_train_end

    return splits


def conservative_probability_size(
    probability: float,
    *,
    max_size: float = 1.0,
    ladder: Sequence[tuple[float, float]] | None = None,
) -> float:
    """Map model probability to a conservative size fraction.

    The returned size is in the same unit as `max_size`, typically 0.0 to 1.0.
    """

    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    if max_size < 0:
        raise ValueError("max_size must be non-negative")

    thresholds = tuple(ladder or (
        (0.55, 0.10),
        (0.60, 0.20),
        (0.65, 0.35),
        (0.70, 0.50),
        (0.75, 0.70),
        (0.80, 1.00),
    ))
    if not thresholds:
        return 0.0

    previous_probability = 0.0
    previous_size = 0.0
    chosen_size = 0.0
    for threshold_probability, size_fraction in thresholds:
        if not 0.0 <= threshold_probability <= 1.0:
            raise ValueError("ladder probabilities must be between 0 and 1")
        if threshold_probability < previous_probability:
            raise ValueError("ladder probabilities must be sorted ascending")
        if size_fraction < previous_size:
            raise ValueError("ladder sizes must be sorted ascending")
        previous_probability = threshold_probability
        previous_size = size_fraction
        if probability >= threshold_probability:
            chosen_size = size_fraction

    return round(chosen_size * max_size, 8)
