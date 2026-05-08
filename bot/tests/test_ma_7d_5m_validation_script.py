from datetime import datetime

from scripts.run_ma_7d_5m_validation import _build_windows, _markdown_report


def test_build_windows_walks_backwards_from_end():
    end = datetime(2026, 5, 8, 12, 0, 0)

    windows = _build_windows(end, days=21, count=2)

    assert windows[0][0] == "recent"
    assert windows[0][2] == end
    assert (windows[0][2] - windows[0][1]).days == 21
    assert windows[1][0] == "prior_1"
    assert windows[1][2] == windows[0][1]


def test_markdown_report_marks_inconsistent_pnl_as_not_demo_ready():
    payload = {
        "created_at": "2026-05-08T12:00:00+00:00",
        "pairs": ["BTC-USDT-SWAP"],
        "timeframe": "5m",
        "window_days": 21,
        "window_count": 1,
        "assumptions": {
            "initial_balance": 10_000.0,
            "leverage": 2,
            "fee_rate": 0.0005,
            "slippage_pct": 0.05,
        },
        "results": [
            {
                "status": "ok",
                "window": "recent",
                "pair": "BTC-USDT-SWAP",
                "scenario": "limited_long",
                "candles": 6049,
                "trade_count": 1,
                "total_pnl": -10.0,
                "return_pct": -0.1,
                "win_rate": 0.0,
                "max_drawdown": 0.01,
                "sharpe_ratio": -1.0,
                "long_trades": 1,
                "short_trades": 0,
            }
        ],
    }

    report = _markdown_report(payload)

    assert "Positive runs: 0/1" in report
    assert "demo 후보 탈락/보류" in report
