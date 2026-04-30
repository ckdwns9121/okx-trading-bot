"""Recommended OKX demo forward-observation setup."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from app.core.demo_profiles import (
    DEMO_RSI_REGIME_LIMITED_PARAMS,
    RISK_LIMITED_RSI_REGIME_STRATEGY,
)

DEFAULT_DEMO_OBSERVATION_PAIRS: tuple[str, ...] = (
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
)
DEFAULT_DEMO_OBSERVATION_TIMEFRAME = "1H"
DEFAULT_DEMO_OBSERVATION_LEVERAGE = 2
MAX_DEMO_TOTAL_DRAWDOWN_PCT = 10.0
MAX_DEMO_POSITION_SIZE_PCT = 10.0


@dataclass(frozen=True)
class DemoObservationConfig:
    """Strategy configuration recommended for paper/demo observation."""

    pair: str
    strategy_name: str = RISK_LIMITED_RSI_REGIME_STRATEGY
    timeframe: str = DEFAULT_DEMO_OBSERVATION_TIMEFRAME
    leverage: int = DEFAULT_DEMO_OBSERVATION_LEVERAGE
    parameters_json: dict[str, Any] | None = None
    is_active: bool = True

    def to_api_payload(self) -> dict[str, Any]:
        """Return the payload accepted by PUT /api/config."""
        return {
            "strategy_name": self.strategy_name,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "parameters_json": deepcopy(self.parameters_json or {}),
            "leverage": self.leverage,
            "is_active": self.is_active,
        }


def build_demo_observation_configs(
    pairs: Iterable[str] = DEFAULT_DEMO_OBSERVATION_PAIRS,
    *,
    is_active: bool = True,
) -> list[dict[str, Any]]:
    """Build safe 1H RSI-regime configs for OKX demo observation."""
    configs: list[dict[str, Any]] = []
    for raw_pair in pairs:
        pair = raw_pair.strip()
        if not pair:
            continue
        config = DemoObservationConfig(
            pair=pair,
            parameters_json=DEMO_RSI_REGIME_LIMITED_PARAMS,
            is_active=is_active,
        )
        configs.append(config.to_api_payload())
    return configs


def validate_demo_observation_settings(settings: Any) -> list[str]:
    """Return blocking safety problems before applying demo observation configs."""
    problems: list[str] = []

    if getattr(settings, "OKX_MODE", None) != "demo":
        problems.append("OKX_MODE must be 'demo' before demo observation configs are applied")

    if getattr(settings, "RISK_FAIL_CLOSED", None) is not True:
        problems.append("RISK_FAIL_CLOSED must be true so risk-check errors block new entries")

    starting_equity = float(getattr(settings, "RISK_STARTING_EQUITY_USD", 0.0) or 0.0)
    if starting_equity <= 0.0:
        problems.append("RISK_STARTING_EQUITY_USD must be greater than 0")

    total_dd = float(getattr(settings, "MAX_TOTAL_DRAWDOWN_PCT", 0.0) or 0.0)
    if total_dd <= 0.0 or total_dd > MAX_DEMO_TOTAL_DRAWDOWN_PCT:
        problems.append(
            f"MAX_TOTAL_DRAWDOWN_PCT must be in (0, {MAX_DEMO_TOTAL_DRAWDOWN_PCT}] for demo observation"
        )

    daily_loss = float(getattr(settings, "MAX_DAILY_LOSS_USD", 0.0) or 0.0)
    monthly_loss = float(getattr(settings, "MAX_MONTHLY_LOSS_USD", 0.0) or 0.0)
    if daily_loss <= 0.0:
        problems.append("MAX_DAILY_LOSS_USD must be greater than 0")
    if monthly_loss <= 0.0:
        problems.append("MAX_MONTHLY_LOSS_USD must be greater than 0")
    if daily_loss > 0.0 and monthly_loss > 0.0 and monthly_loss < daily_loss:
        problems.append("MAX_MONTHLY_LOSS_USD must be greater than or equal to MAX_DAILY_LOSS_USD")

    max_position = float(getattr(settings, "MAX_POSITION_SIZE_PCT", 0.0) or 0.0)
    if max_position <= 0.0 or max_position > MAX_DEMO_POSITION_SIZE_PCT:
        problems.append(
            f"MAX_POSITION_SIZE_PCT must be in (0, {MAX_DEMO_POSITION_SIZE_PCT}] for the first demo phase"
        )

    return problems
