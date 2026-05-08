from scripts.run_all_strategy_backtest_comparison import conclusion_lines, summarize, verdict_for


def test_summarize_ranks_raw_pnl_but_marks_high_drawdown_as_high_risk():
    results = [
        {
            "strategy": "raw_winner",
            "status": "ok",
            "total_pnl": 1000.0,
            "max_drawdown": 0.75,
            "profit_factor": 1.2,
            "sharpe_ratio": 0.5,
            "win_rate": 0.5,
            "trade_count": 10,
            "pair": "ETH-USDT-SWAP",
            "timeframe": "15m",
        },
        {
            "strategy": "stable",
            "status": "ok",
            "total_pnl": 200.0,
            "max_drawdown": 0.2,
            "profit_factor": 1.4,
            "sharpe_ratio": 1.0,
            "win_rate": 0.6,
            "trade_count": 5,
            "pair": "BTC-USDT-SWAP",
            "timeframe": "1H",
        },
    ]

    summaries = summarize(results)

    by_strategy = {row["strategy"]: row for row in summaries}
    assert by_strategy["raw_winner"]["verdict"] == "고위험 관찰"
    assert by_strategy["stable"]["verdict"] == "paper 후보"
    assert summaries[0]["strategy"] == "stable"


def test_verdict_for_rejects_negative_total_pnl():
    verdict = verdict_for(
        {
            "ok_runs": 3,
            "positive_runs": 1,
            "total_pnl": -10.0,
            "positive_rate_pct": 33.3,
            "max_drawdown_pct": 5.0,
        }
    )

    assert verdict == "탈락/보류"


def test_conclusion_lines_warn_when_raw_winner_has_large_drawdown():
    payload = {
        "summaries": [
            {
                "strategy": "example_rsi",
                "verdict": "고위험 관찰",
                "total_pnl": 1000.0,
                "max_drawdown_pct": 97.44,
                "positive_runs": 4,
                "ok_runs": 6,
            },
            {
                "strategy": "rsi_bollinger_regime",
                "verdict": "고위험 관찰",
                "total_pnl": 100.0,
                "max_drawdown_pct": 68.49,
                "positive_runs": 5,
                "ok_runs": 6,
            },
        ]
    }

    lines = conclusion_lines(payload)

    assert any("example_rsi" in line and "바로 demo/live 후보로 보지 않는다" in line for line in lines)
    assert any("risk_profile=limited" in line for line in lines)
