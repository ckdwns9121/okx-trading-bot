from __future__ import annotations

import pytest

from app.core.trend_following import (
    PaperBook,
    apply_paper_fill,
    backtest_trend_following,
    compute_sma,
    evaluate_trend,
    plan_rebalance,
)


def test_sma_requires_enough_history() -> None:
    assert compute_sma([1.0, 2.0], 3) is None
    assert compute_sma([1.0, 2.0, 3.0], 3) == pytest.approx(2.0)


def test_trend_signal_votes_and_target() -> None:
    # 30 rising closes: price above every MA.
    closes = [100.0 + i for i in range(30)]
    signal = evaluate_trend("BTC-USDT", closes, ma_periods=(5, 10, 20))
    assert signal.ready
    assert signal.votes == 3
    assert signal.target_fraction == pytest.approx(1.0)

    # Falling closes: price below every MA.
    falling = [200.0 - i for i in range(30)]
    signal = evaluate_trend("BTC-USDT", falling, ma_periods=(5, 10, 20))
    assert signal.votes == 0
    assert signal.target_fraction == 0.0


def test_trend_signal_not_ready_without_history() -> None:
    signal = evaluate_trend("BTC-USDT", [100.0] * 10, ma_periods=(5, 20))
    assert not signal.ready


def test_plan_rebalance_buy_and_sell() -> None:
    buy = plan_rebalance(
        inst_id="BTC-USDT",
        target_fraction=1.0,
        allocation_usd=1000.0,
        current_quantity=0.0,
        price=100.0,
        min_trade_usd=25.0,
    )
    assert buy is not None and buy.side == "buy"
    assert buy.quantity == pytest.approx(10.0)

    sell = plan_rebalance(
        inst_id="BTC-USDT",
        target_fraction=0.0,
        allocation_usd=1000.0,
        current_quantity=10.0,
        price=100.0,
    )
    assert sell is not None and sell.side == "sell"
    assert sell.quantity == pytest.approx(10.0)


def test_plan_rebalance_skips_small_deltas_and_caps_sells() -> None:
    assert (
        plan_rebalance(
            inst_id="BTC-USDT",
            target_fraction=1.0,
            allocation_usd=1000.0,
            current_quantity=9.9,
            price=100.0,
            min_trade_usd=25.0,
        )
        is None
    )

    capped = plan_rebalance(
        inst_id="BTC-USDT",
        target_fraction=0.0,
        allocation_usd=1000.0,
        current_quantity=1.0,
        price=100.0,
    )
    assert capped is not None
    assert capped.quantity == pytest.approx(1.0)


def test_paper_fill_roundtrip_with_fees() -> None:
    book = PaperBook(cash_usd=1000.0)
    apply_paper_fill(
        book, inst_id="BTC-USDT", side="buy", quantity=5.0, price=100.0, fee_pct=0.1
    )
    assert book.cash_usd == pytest.approx(1000.0 - 500.0 - 0.5)
    assert book.position("BTC-USDT").quantity == pytest.approx(5.0)

    trade = apply_paper_fill(
        book, inst_id="BTC-USDT", side="sell", quantity=5.0, price=110.0, fee_pct=0.1
    )
    assert trade["realized_pnl_usd"] == pytest.approx(5.0 * 10.0 - 0.55)
    assert book.position("BTC-USDT").quantity == 0.0
    assert book.realized_pnl_usd == pytest.approx(49.45)


def test_paper_fill_rejects_overdraft_and_oversell() -> None:
    book = PaperBook(cash_usd=100.0)
    with pytest.raises(ValueError):
        apply_paper_fill(
            book, inst_id="BTC-USDT", side="buy", quantity=2.0, price=100.0, fee_pct=0.1
        )
    with pytest.raises(ValueError):
        apply_paper_fill(
            book, inst_id="BTC-USDT", side="sell", quantity=1.0, price=100.0, fee_pct=0.1
        )


def test_paper_book_payload_roundtrip() -> None:
    book = PaperBook(cash_usd=500.0)
    apply_paper_fill(
        book, inst_id="ETH-USDT", side="buy", quantity=1.0, price=100.0, fee_pct=0.0
    )
    restored = PaperBook.from_payload(book.to_payload())
    assert restored.cash_usd == pytest.approx(book.cash_usd)
    assert restored.position("ETH-USDT").quantity == pytest.approx(1.0)


def _uptrend_candles(days: int, start: float = 100.0, step: float = 1.0) -> list[dict]:
    rows = []
    price = start
    for _ in range(days):
        rows.append({"open": price, "close": price + step})
        price += step
    return rows


def _crash_candles(days_up: int, days_down: int) -> list[dict]:
    rows = _uptrend_candles(days_up)
    price = rows[-1]["close"]
    for _ in range(days_down):
        rows.append({"open": price, "close": price * 0.97})
        price *= 0.97
    return rows


def test_backtest_uptrend_stays_invested_and_beats_cash() -> None:
    result = backtest_trend_following(
        {"BTC-USDT": _uptrend_candles(80)},
        ma_periods=(5, 10, 20),
        allocation_usd_per_inst=1000.0,
    )
    assert result["total_return_pct"] > 0.0
    assert result["trade_count"] >= 1


def test_backtest_exits_in_crash_with_smaller_drawdown_than_buy_hold() -> None:
    result = backtest_trend_following(
        {"BTC-USDT": _crash_candles(60, 60)},
        ma_periods=(5, 10, 20),
        allocation_usd_per_inst=1000.0,
    )
    assert result["max_drawdown_pct"] < result["buy_hold_max_drawdown_pct"]


def test_backtest_requires_enough_history() -> None:
    with pytest.raises(ValueError):
        backtest_trend_following(
            {"BTC-USDT": _uptrend_candles(10)},
            ma_periods=(5, 10, 20),
        )
