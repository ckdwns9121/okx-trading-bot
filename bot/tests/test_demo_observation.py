from app.config import Settings
from app.core.demo_observation import (
    DEFAULT_DEMO_OBSERVATION_LEVERAGE,
    DEFAULT_DEMO_OBSERVATION_TIMEFRAME,
    build_demo_observation_configs,
    validate_demo_observation_settings,
)
from app.core.demo_profiles import RISK_LIMITED_RSI_REGIME_STRATEGY


def _settings(**overrides):
    values = {
        "OKX_API_KEY": "dummy",
        "OKX_SECRET": "dummy",
        "OKX_PASSPHRASE": "dummy",
        "OKX_MODE": "demo",
        "RISK_FAIL_CLOSED": True,
        "RISK_STARTING_EQUITY_USD": 10_000.0,
        "MAX_TOTAL_DRAWDOWN_PCT": 10.0,
        "MAX_DAILY_LOSS_USD": 200.0,
        "MAX_MONTHLY_LOSS_USD": 1_000.0,
        "MAX_POSITION_SIZE_PCT": 10.0,
    }
    values.update(overrides)
    return Settings(**values)


def test_build_demo_observation_configs_use_safe_1h_limited_profile():
    configs = build_demo_observation_configs(["BTC-USDT-SWAP", "", "ETH-USDT-SWAP"])

    assert [config["pair"] for config in configs] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    for config in configs:
        assert config["strategy_name"] == RISK_LIMITED_RSI_REGIME_STRATEGY
        assert config["timeframe"] == DEFAULT_DEMO_OBSERVATION_TIMEFRAME
        assert config["leverage"] == DEFAULT_DEMO_OBSERVATION_LEVERAGE
        assert config["is_active"] is True
        assert config["parameters_json"]["risk_profile"] == "limited"
        assert config["parameters_json"]["tail_risk_overlay_enabled"] is True


def test_demo_observation_settings_accept_safe_demo_defaults():
    assert validate_demo_observation_settings(_settings()) == []


def test_demo_observation_settings_reject_live_or_loose_risk_settings():
    problems = validate_demo_observation_settings(
        _settings(
            OKX_MODE="live",
            RISK_FAIL_CLOSED=False,
            MAX_TOTAL_DRAWDOWN_PCT=25.0,
            MAX_POSITION_SIZE_PCT=50.0,
        )
    )

    assert any("OKX_MODE" in problem for problem in problems)
    assert any("RISK_FAIL_CLOSED" in problem for problem in problems)
    assert any("MAX_TOTAL_DRAWDOWN_PCT" in problem for problem in problems)
    assert any("MAX_POSITION_SIZE_PCT" in problem for problem in problems)
