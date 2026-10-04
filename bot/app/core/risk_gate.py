"""Pre-trade risk gate and persistent kill switch.

Every order intent MUST pass through ``RiskGate.validate`` before it is sent
to the exchange. The gate is engine-agnostic: callers describe the order and
current account state, the gate answers allow/reject with per-check details.

The kill switch persists across process restarts (JSON state file) so a
tripped switch keeps blocking new entries until a human resets it.
Reduce-only (closing) orders are still allowed while tripped, because the
safe reaction to an incident is flattening, not freezing.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OrderIntent:
    inst_id: str
    side: str  # "buy" | "sell"
    notional_usd: float
    reference_price: float
    execution_price: float
    reduce_only: bool = False


@dataclass(frozen=True)
class AccountState:
    """Caller-supplied snapshot of the account at decision time."""

    instrument_notional_usd: dict[str, float] = field(default_factory=dict)
    total_exposure_usd: float = 0.0
    daily_realized_pnl_usd: float = 0.0


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional_usd: float = 1000.0
    max_instrument_notional_usd: float = 2000.0
    max_total_exposure_usd: float = 4000.0
    max_price_deviation_pct: float = 1.0
    max_daily_loss_usd: float = 100.0
    max_orders_per_minute: int = 6

    def validate(self) -> None:
        if self.max_order_notional_usd <= 0:
            raise ValueError("max_order_notional_usd must be positive")
        if self.max_instrument_notional_usd <= 0:
            raise ValueError("max_instrument_notional_usd must be positive")
        if self.max_total_exposure_usd <= 0:
            raise ValueError("max_total_exposure_usd must be positive")
        if self.max_price_deviation_pct <= 0:
            raise ValueError("max_price_deviation_pct must be positive")
        if self.max_daily_loss_usd <= 0:
            raise ValueError("max_daily_loss_usd must be positive")
        if self.max_orders_per_minute <= 0:
            raise ValueError("max_orders_per_minute must be positive")


@dataclass(frozen=True)
class RiskCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    checks: tuple[RiskCheck, ...]

    @property
    def rejection_reasons(self) -> list[str]:
        return [f"{check.name}: {check.detail}" for check in self.checks if not check.passed]


class KillSwitch:
    """File-persisted kill switch shared by every process on the same volume."""

    def __init__(self, state_path: str | Path) -> None:
        self._state_path = Path(state_path)

    @property
    def state_path(self) -> Path:
        return self._state_path

    def status(self) -> dict[str, Any]:
        state = self._read()
        return {
            "tripped": bool(state.get("tripped", False)),
            "reason": state.get("reason"),
            "source": state.get("source"),
            "changed_at": state.get("changed_at"),
        }

    def is_tripped(self) -> bool:
        return bool(self._read().get("tripped", False))

    def trip(self, *, reason: str, source: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("kill switch trip requires a reason")
        state = {
            "tripped": True,
            "reason": reason,
            "source": source,
            "changed_at": _utcnow().isoformat(),
        }
        self._write(state)
        return state

    def reset(self, *, source: str) -> dict[str, Any]:
        state = {
            "tripped": False,
            "reason": None,
            "source": source,
            "changed_at": _utcnow().isoformat(),
        }
        self._write(state)
        return state

    def _read(self) -> dict[str, Any]:
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return {"tripped": True, "reason": "kill switch state file is corrupt"}
            return data
        except FileNotFoundError:
            return {"tripped": False}
        except (OSError, json.JSONDecodeError):
            # Fail closed: unreadable state must never silently allow trading.
            return {"tripped": True, "reason": "kill switch state file is unreadable"}

    def _write(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self._state_path.parent), prefix=".kill_switch_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._state_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


class RiskGate:
    def __init__(
        self,
        *,
        limits: RiskLimits,
        kill_switch: KillSwitch,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        limits.validate()
        self._limits = limits
        self._kill_switch = kill_switch
        self._clock = clock
        self._recent_order_times: deque[datetime] = deque()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    def validate(self, intent: OrderIntent, account: AccountState) -> RiskDecision:
        checks: list[RiskCheck] = []

        checks.append(self._check_kill_switch(intent))
        checks.append(self._check_sanity(intent))

        # A rejected sanity check makes the numeric checks meaningless.
        if all(check.passed for check in checks):
            checks.append(self._check_order_notional(intent))
            checks.append(self._check_price_deviation(intent))
            checks.append(self._check_instrument_limit(intent, account))
            checks.append(self._check_total_exposure(intent, account))
            checks.append(self._check_daily_loss(intent, account))
            checks.append(self._check_order_rate(intent))

        allowed = all(check.passed for check in checks)
        if allowed:
            self._recent_order_times.append(self._clock())
        return RiskDecision(allowed=allowed, checks=tuple(checks))

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #

    def _check_kill_switch(self, intent: OrderIntent) -> RiskCheck:
        status = self._kill_switch.status()
        if status["tripped"] and not intent.reduce_only:
            return RiskCheck(
                name="kill_switch",
                passed=False,
                detail=f"kill switch tripped ({status.get('reason') or 'no reason recorded'})",
            )
        return RiskCheck(name="kill_switch", passed=True, detail="not tripped or reduce-only order")

    def _check_sanity(self, intent: OrderIntent) -> RiskCheck:
        if intent.side not in {"buy", "sell"}:
            return RiskCheck(name="sanity", passed=False, detail=f"unknown side {intent.side!r}")
        if intent.notional_usd <= 0:
            return RiskCheck(name="sanity", passed=False, detail="notional must be positive")
        if intent.reference_price <= 0 or intent.execution_price <= 0:
            return RiskCheck(name="sanity", passed=False, detail="prices must be positive")
        return RiskCheck(name="sanity", passed=True, detail="ok")

    def _check_order_notional(self, intent: OrderIntent) -> RiskCheck:
        limit = self._limits.max_order_notional_usd
        if intent.notional_usd > limit:
            return RiskCheck(
                name="max_order_notional",
                passed=False,
                detail=f"order notional ${intent.notional_usd:,.2f} exceeds limit ${limit:,.2f}",
            )
        return RiskCheck(name="max_order_notional", passed=True, detail="within limit")

    def _check_price_deviation(self, intent: OrderIntent) -> RiskCheck:
        # Flattening is the safe reaction to a fast market; a reduce-only order
        # must never be refused because price already moved. Same rationale as
        # letting reduce-only orders through a tripped kill switch.
        if intent.reduce_only:
            return RiskCheck(name="price_deviation", passed=True, detail="reduce-only order")
        deviation_pct = abs((intent.execution_price / intent.reference_price) - 1.0) * 100.0
        limit = self._limits.max_price_deviation_pct
        if deviation_pct > limit:
            return RiskCheck(
                name="price_deviation",
                passed=False,
                detail=(
                    f"execution price deviates {deviation_pct:.3f}% from decision price"
                    f" (limit {limit:.3f}%)"
                ),
            )
        return RiskCheck(name="price_deviation", passed=True, detail="within limit")

    def _check_instrument_limit(self, intent: OrderIntent, account: AccountState) -> RiskCheck:
        if intent.reduce_only:
            return RiskCheck(name="instrument_limit", passed=True, detail="reduce-only order")
        current = float(account.instrument_notional_usd.get(intent.inst_id, 0.0))
        projected = current + intent.notional_usd
        limit = self._limits.max_instrument_notional_usd
        if projected > limit:
            return RiskCheck(
                name="instrument_limit",
                passed=False,
                detail=(
                    f"{intent.inst_id} projected notional ${projected:,.2f}"
                    f" exceeds limit ${limit:,.2f}"
                ),
            )
        return RiskCheck(name="instrument_limit", passed=True, detail="within limit")

    def _check_total_exposure(self, intent: OrderIntent, account: AccountState) -> RiskCheck:
        if intent.reduce_only:
            return RiskCheck(name="total_exposure", passed=True, detail="reduce-only order")
        projected = float(account.total_exposure_usd) + intent.notional_usd
        limit = self._limits.max_total_exposure_usd
        if projected > limit:
            return RiskCheck(
                name="total_exposure",
                passed=False,
                detail=f"projected exposure ${projected:,.2f} exceeds limit ${limit:,.2f}",
            )
        return RiskCheck(name="total_exposure", passed=True, detail="within limit")

    def _check_daily_loss(self, intent: OrderIntent, account: AccountState) -> RiskCheck:
        loss_limit = self._limits.max_daily_loss_usd
        pnl = float(account.daily_realized_pnl_usd)
        if pnl <= -loss_limit and not intent.reduce_only:
            self._kill_switch.trip(
                reason=(
                    f"daily realized loss ${-pnl:,.2f} reached limit ${loss_limit:,.2f}"
                ),
                source="risk_gate",
            )
            return RiskCheck(
                name="daily_loss",
                passed=False,
                detail=f"daily loss ${-pnl:,.2f} breached limit ${loss_limit:,.2f}; kill switch tripped",
            )
        return RiskCheck(name="daily_loss", passed=True, detail="within limit")

    def _check_order_rate(self, intent: OrderIntent) -> RiskCheck:
        del intent
        now = self._clock()
        window_start_age = 60.0
        while self._recent_order_times and (
            (now - self._recent_order_times[0]).total_seconds() > window_start_age
        ):
            self._recent_order_times.popleft()
        limit = self._limits.max_orders_per_minute
        if len(self._recent_order_times) >= limit:
            return RiskCheck(
                name="order_rate",
                passed=False,
                detail=f"{len(self._recent_order_times)} orders in the last minute (limit {limit})",
            )
        return RiskCheck(name="order_rate", passed=True, detail="within limit")


def build_risk_gate_from_settings(settings: Any) -> RiskGate:
    """Construct the gate from app settings (see app.config.Settings)."""

    limits = RiskLimits(
        max_order_notional_usd=float(settings.RISK_MAX_ORDER_NOTIONAL_USD),
        max_instrument_notional_usd=float(settings.RISK_MAX_INSTRUMENT_NOTIONAL_USD),
        max_total_exposure_usd=float(settings.RISK_MAX_TOTAL_EXPOSURE_USD),
        max_price_deviation_pct=float(settings.RISK_MAX_PRICE_DEVIATION_PCT),
        max_daily_loss_usd=float(settings.MAX_DAILY_LOSS_USD),
        max_orders_per_minute=int(settings.RISK_MAX_ORDERS_PER_MINUTE),
    )
    kill_switch = KillSwitch(settings.RISK_KILL_SWITCH_FILE)
    return RiskGate(limits=limits, kill_switch=kill_switch)
