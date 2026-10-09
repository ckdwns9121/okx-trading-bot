from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.donchian_majors import DonchianParams
from app.core.donchian_trader import (
    Decision,
    Fill,
    Sleeve,
    apply_fill,
    candles_to_bars,
    client_order_id,
    decide,
    expected_latest_bar_ts,
    floor_to_step,
    is_fresh,
    reconcile,
)

DAY = 86_400_000
T0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def candles(closes: list[float], *, last_confirmed: bool = True) -> list[dict]:
    out = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else c
        out.append({"timestamp": str(T0 + k * DAY), "open": o, "high": max(o, c) * 1.002, "low": min(o, c) * 0.998,
                    "close": c, "confirm": "1"})
    if not last_confirmed:
        out[-1]["confirm"] = "0"
    return out


def noisy(n: int, base: float = 100.0) -> list[float]:
    return [base + (1.0 if k % 2 else -1.0) for k in range(n)]


def test_candles_to_bars_drops_unconfirmed_and_sorts() -> None:
    c = candles(noisy(10), last_confirmed=False)
    b = candles_to_bars("BTC-USDT", list(reversed(c)))
    assert len(b.ts) == 9
    assert b.ts == sorted(b.ts)


def test_freshness_uses_utc_yesterday() -> None:
    now = datetime(2026, 10, 9, 0, 5, tzinfo=timezone.utc)
    yday = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp() * 1000)
    assert expected_latest_bar_ts(now) == yday
    assert is_fresh(yday, now)
    assert not is_fresh(yday - DAY, now)


def test_decide_buys_on_breakout_with_risk_sizing_and_sells_on_breakdown() -> None:
    p = DonchianParams(55, 20, 20, 2.0, risk_pct=5.0)
    sleeve = Sleeve("SOL-USDT", cash_usd=1000.0)
    up = noisy(60) + [130.0]
    d = decide(candles_to_bars("SOL-USDT", candles(up)), sleeve, p, min_notional=10)
    assert d.action == "buy" and d.reason == "breakout"
    assert 0 < d.fraction <= 1 and d.quote_to_spend == pytest.approx(1000 * d.fraction)

    holding = Sleeve("SOL-USDT", cash_usd=0.0, qty=5.0, entry_px=130.0, entry_atr=2.0)
    down = noisy(60) + [130.0] * 5 + [90.0]
    d2 = decide(candles_to_bars("SOL-USDT", candles(down)), holding, p, min_notional=10)
    assert d2.action == "sell" and d2.base_to_sell == 5.0

    idle = decide(candles_to_bars("SOL-USDT", candles(noisy(80))), Sleeve("SOL-USDT", 1000.0), p, min_notional=10)
    assert idle.action == "none" and idle.reason == "no_signal"


def test_client_order_id_is_stable_and_okx_valid() -> None:
    a = client_order_id("BTC-USDT", T0, "buy")
    assert a == client_order_id("BTC-USDT", T0, "buy")
    assert a != client_order_id("BTC-USDT", T0 + DAY, "buy")
    assert a != client_order_id("BTC-USDT", T0, "sell")
    assert a.isalnum() and len(a) <= 32


def test_reconcile_ignores_baseline_and_flags_shortfall_as_critical() -> None:
    sleeves = {"BTC-USDT": Sleeve("BTC-USDT", 0.0, qty=0.01), "ETH-USDT": Sleeve("ETH-USDT", 1000.0)}
    tol = {"BTC": 1e-6, "ETH": 1e-6}
    ok = reconcile(sleeves, {"BTC": 1.01, "ETH": 1.0}, {"BTC": 1.0, "ETH": 1.0}, tol)
    assert ok == []
    short = reconcile(sleeves, {"BTC": 1.005, "ETH": 1.0}, {"BTC": 1.0, "ETH": 1.0}, tol)
    assert len(short) == 1 and short[0].critical and short[0].ccy == "BTC"
    excess = reconcile(sleeves, {"BTC": 1.01, "ETH": 1.5}, {"BTC": 1.0, "ETH": 1.0}, tol)
    assert len(excess) == 1 and not excess[0].critical


def test_apply_fill_buy_fee_in_base_then_sell_fee_in_quote() -> None:
    s = Sleeve("ETH-USDT", cash_usd=1000.0)
    buy_dec = Decision("ETH-USDT", T0, "buy", "breakout", 2000.0, 50.0, quote_to_spend=500.0, fraction=0.5)
    rec = apply_fill(s, Fill("buy", 0.25, 2000.0, -0.00025, "ETH"), fill_ts=T0 + 1, decision=buy_dec)
    assert s.qty == pytest.approx(0.24975)
    assert s.cash_usd == pytest.approx(500.0)
    assert s.entry_atr == 50.0 and rec["fee_usd"] == pytest.approx(0.5)

    sell_dec = Decision("ETH-USDT", T0 + DAY, "sell", "channel", 2200.0, 50.0, base_to_sell=s.qty)
    qty = floor_to_step(s.qty, 0.0001)
    rec2 = apply_fill(s, Fill("sell", qty, 2200.0, -0.55, "USDT"), fill_ts=T0 + DAY + 1, decision=sell_dec)
    assert rec2["realized_pnl_usd"] == pytest.approx(qty * 2200.0 - 0.55 - qty * (500.0 / 0.24975), rel=1e-6)
    assert s.qty < 0.0001 and s.entry_px is None
    assert s.cash_usd > 1000.0  # profitable round trip


def test_floor_to_step() -> None:
    assert floor_to_step(0.123456, 0.0001) == pytest.approx(0.1234)
    assert floor_to_step(5.0, 1.0) == 5.0
