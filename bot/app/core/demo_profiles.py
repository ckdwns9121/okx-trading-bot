"""Safe demo/paper strategy profile defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

RISK_LIMITED_RSI_REGIME_STRATEGY = "rsi_bollinger_regime"

# Keep pair-manager overlay keys prefixed with ``risk_`` where a strategy may
# already use the unprefixed name for signal-level TP/SL/trailing behavior.
DEMO_RSI_REGIME_LIMITED_PARAMS: dict[str, Any] = {
    "risk_profile": "limited",
    "tail_risk_overlay_enabled": True,
    "risk_hard_stop_pct": 2.0,
    "risk_trailing_activation_pct": 1.5,
    "risk_trailing_stop_pct": 0.8,
    "time_stop_candles": 12,
    "time_stop_edge_pct": 0.05,
    "degrade_after_losses": 2,
    "pause_after_losses": 3,
    "pause_minutes": 1440,
}


def apply_demo_strategy_defaults(
    *,
    strategy_name: str,
    params: dict[str, Any] | None,
    okx_mode: str,
) -> dict[str, Any]:
    """Return params with safe demo defaults for supported strategies.

    Live mode is intentionally left untouched. In demo mode the RSI/Bollinger
    regime strategy is forced onto the risk-limited profile, while user-supplied
    overlay thresholds may still override the default risk thresholds.
    """
    current = deepcopy(params or {})
    if okx_mode != "demo" or strategy_name != RISK_LIMITED_RSI_REGIME_STRATEGY:
        return current

    merged = {**DEMO_RSI_REGIME_LIMITED_PARAMS, **current}
    merged["risk_profile"] = "limited"
    merged["tail_risk_overlay_enabled"] = True
    return merged
