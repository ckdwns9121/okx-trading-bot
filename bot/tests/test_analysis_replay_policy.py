from app.core.analysis_experiment_runner import replay_passes_policy


def test_replay_policy_exact_boundary_passes():
    original = {"total_pnl": 100.0, "sharpe_ratio": 1.0, "trade_count": 10.0}
    replay = {"total_pnl": 95.01, "sharpe_ratio": 1.14, "trade_count": 9.0}
    assert replay_passes_policy(original, replay) is True


def test_replay_policy_below_boundary_fails():
    original = {"total_pnl": 100.0, "sharpe_ratio": 1.0, "trade_count": 10.0}
    replay = {"total_pnl": 94.9, "sharpe_ratio": 1.16, "trade_count": 8.8}
    assert replay_passes_policy(original, replay) is False
