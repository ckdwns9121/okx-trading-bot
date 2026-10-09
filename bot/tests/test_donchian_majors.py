from __future__ import annotations

from datetime import datetime, timezone

from app.core.donchian_majors import Bars, DonchianParams, SmaParams, backtest_portfolio, run_sleeve

DAY = 86_400_000
T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def bars(closes: list[float], inst: str = "X-USDT") -> Bars:
    ts = [T0 + i * DAY for i in range(len(closes))]
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
    return Bars(inst, ts, opens, highs, lows, closes)


def test_breakout_enters_next_open_and_channel_exit_sells() -> None:
    flat = [100.0] * 60
    rally = [100 + 2 * k for k in range(1, 31)]  # breaks the 55d high on day 60
    fall = [rally[-1] - 5 * k for k in range(1, 20)]
    b = bars(flat + rally + fall)
    eq, trades = run_sleeve(b, rule="donchian", params=DonchianParams(55, 20, 20, None), start_ts=T0, end_ts=None, cash=1000, fee_pct=0.0)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_ts == b.ts[61]  # decided on bar 60 close, filled at bar 61 open
    assert t.entry_px == b.open[61]
    assert t.exit_ts is not None and t.reason == "channel"
    assert t.pnl_pct > 0
    assert len(eq) == len(b.ts)


def test_atr_stop_cuts_a_false_breakout() -> None:
    flat = [100.0 + (0.5 if k % 2 else -0.5) for k in range(60)]
    pop = [104.0]
    dump = [104 - 3 * k for k in range(1, 6)]
    b = bars(flat + pop + dump + [90.0] * 10)
    _, trades = run_sleeve(b, rule="donchian", params=DonchianParams(55, 20, 20, 1.0), start_ts=T0, end_ts=None, cash=1000, fee_pct=0.0)
    assert trades and trades[0].reason == "atr_stop"
    assert trades[0].pnl_pct < 0


def test_sma_filter_and_portfolio_benchmarks() -> None:
    up = bars([100 + k for k in range(200)], "A-USDT")
    down = bars([300 - k for k in range(200)], "B-USDT")
    pf = {"A-USDT": up, "B-USDT": down}
    hold = backtest_portfolio(pf, rule="hold", params=None, start_ts=T0, fee_pct=0.0)
    sma = backtest_portfolio(pf, rule="sma", params=SmaParams(100), start_ts=T0, fee_pct=0.0)
    assert hold["per_inst"]["A-USDT"]["cagr_pct"] > 0 > hold["per_inst"]["B-USDT"]["cagr_pct"]
    assert sma["per_inst"]["B-USDT"]["round_trips"] == 0  # never above its SMA → never bought
    assert sma["per_inst"]["B-USDT"]["max_drawdown_pct"] == 0.0
    assert "A-USDT" in sma["open_positions"]


def test_fees_reduce_results() -> None:
    b = {"X-USDT": bars([100.0] * 60 + [100 + 2 * k for k in range(1, 31)] + [160 - 5 * k for k in range(1, 20)])}
    free = backtest_portfolio(b, rule="donchian", params=DonchianParams(55, 20, 20, None), start_ts=T0, fee_pct=0.0)
    paid = backtest_portfolio(b, rule="donchian", params=DonchianParams(55, 20, 20, None), start_ts=T0, fee_pct=0.3)
    assert paid["final_equity_usd"] < free["final_equity_usd"]
