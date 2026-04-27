"""Multi-pair orchestration with per-pair asyncio task supervision."""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.core.order_manager import OrderManager
from app.core.runtime_events import add_event
from app.core.strategy_base import BaseStrategy, Signal, TradingContext, TradeSignal
from app.core.strategy_registry import StrategyRegistry
from app.db import repository as repo
from app.exchange.okx_client import OKXClient
from app.logging_config import get_logger
from app.models.trade import Trade

logger = get_logger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (10.0, 30.0, 60.0)
_POLL_INTERVAL_SECONDS: float = 60.0
_EDGE_REASON_RE = re.compile(r"edge=([-+]?\d+(?:\.\d+)?)%")


@dataclass
class PairStatus:
    pair: str
    strategy_name: str
    timeframe: str
    status: str
    leverage: int
    last_candle_ts: Optional[str] = None
    retry_count: int = 0
    last_signal: Optional[str] = None
    error: Optional[str] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PairRiskPolicy:
    enabled: bool = False
    hard_stop_pct: float = 0.35
    trailing_activation_pct: float = 0.25
    trailing_stop_pct: float = 0.18
    time_stop_candles: int = 8
    time_stop_edge_pct: float = 0.03
    degrade_after_losses: int = 2
    pause_after_losses: int = 3
    degrade_size_scale: float = 0.5
    pause_minutes: int = 120


@dataclass
class PairRiskState:
    tracked_direction: Optional[str] = None
    bars_held: int = 0
    peak_price: Optional[float] = None
    trough_price: Optional[float] = None
    trailing_armed: bool = False

    losing_streak: int = 0
    size_scale: float = 1.0
    cooldown_until: Optional[datetime] = None
    last_recorded_trade_id: Optional[int] = None


class PairManager:
    def __init__(
        self,
        okx_client: OKXClient,
        session_factory,
        order_manager: OrderManager,
        strategy_registry: StrategyRegistry,
    ) -> None:
        self._client = okx_client
        self._session_factory = session_factory
        self._order_manager = order_manager
        self._registry = strategy_registry
        self._pair_tasks: dict[str, asyncio.Task] = {}
        self._pair_status: dict[str, PairStatus] = {}
        self._pair_risk_policy: dict[str, PairRiskPolicy] = {}
        self._pair_risk_state: dict[str, PairRiskState] = {}

    async def add_pair(
        self,
        pair: str,
        strategy_name: str,
        leverage: int,
        timeframe: str = "1m",
        params: Optional[dict] = None,
    ) -> None:
        if pair in self._pair_tasks and not self._pair_tasks[pair].done():
            logger.warning("pair_already_running", pair=pair)
            return

        strategy_cls = self._registry.get(strategy_name)
        strategy: BaseStrategy = strategy_cls()
        strategy.configure(params or {})
        risk_policy = self._build_risk_policy(strategy_name=strategy_name, params=params or {})

        self._pair_status[pair] = PairStatus(
            pair=pair,
            strategy_name=strategy_name,
            timeframe=timeframe,
            status="running",
            leverage=leverage,
        )
        self._pair_risk_policy[pair] = risk_policy
        self._pair_risk_state[pair] = PairRiskState()

        task = asyncio.create_task(
            self._run_pair(pair, strategy, leverage, timeframe),
            name=f"pair-{pair}",
        )
        self._pair_tasks[pair] = task
        logger.info(
            "pair_added",
            pair=pair,
            strategy=strategy_name,
            leverage=leverage,
            timeframe=timeframe,
        )
        add_event(
            event="pair_added",
            pair=pair,
            strategy=strategy_name,
            timeframe=timeframe,
            details={
                "leverage": leverage,
                "params": params or {},
                "risk_overlay": {
                    "enabled": risk_policy.enabled,
                    "hard_stop_pct": risk_policy.hard_stop_pct,
                    "trailing_activation_pct": risk_policy.trailing_activation_pct,
                    "trailing_stop_pct": risk_policy.trailing_stop_pct,
                    "time_stop_candles": risk_policy.time_stop_candles,
                    "time_stop_edge_pct": risk_policy.time_stop_edge_pct,
                    "degrade_after_losses": risk_policy.degrade_after_losses,
                    "pause_after_losses": risk_policy.pause_after_losses,
                    "degrade_size_scale": risk_policy.degrade_size_scale,
                    "pause_minutes": risk_policy.pause_minutes,
                },
            },
            message="Pair task started",
        )

    async def remove_pair(self, pair: str) -> None:
        task = self._pair_tasks.get(pair)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        async with self._session_factory() as session:
            position = await repo.get_position(session, pair)
        if position is not None:
            logger.info("pair_remove_closing_position", pair=pair)
            strategy_name = self._pair_status.get(pair).strategy_name if pair in self._pair_status else None
            await self._order_manager.close_position(pair, strategy_name=strategy_name)

        self._pair_tasks.pop(pair, None)
        self._pair_risk_policy.pop(pair, None)
        self._pair_risk_state.pop(pair, None)
        if pair in self._pair_status:
            self._pair_status[pair].status = "stopped"
            self._pair_status[pair].last_updated = datetime.now(timezone.utc)

        logger.info("pair_removed", pair=pair)
        add_event(event="pair_removed", pair=pair, message="Pair task stopped")

    def get_status(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for pair, status in self._pair_status.items():
            risk_policy = self._pair_risk_policy.get(pair, PairRiskPolicy())
            risk_state = self._pair_risk_state.get(pair, PairRiskState())
            out[pair] = {
                "strategy_name": status.strategy_name,
                "status": status.status,
                "timeframe": status.timeframe,
                "leverage": status.leverage,
                "retry_count": status.retry_count,
                "last_candle_ts": status.last_candle_ts,
                "last_signal": status.last_signal,
                "error": status.error,
                "last_updated": status.last_updated.isoformat(),
                "risk": {
                    "enabled": risk_policy.enabled,
                    "losing_streak": risk_state.losing_streak,
                    "size_scale": risk_state.size_scale,
                    "cooldown_until": (
                        risk_state.cooldown_until.isoformat() if risk_state.cooldown_until else None
                    ),
                },
            }
        return out

    @staticmethod
    def _normalize_direction(direction: str | None) -> str:
        v = (direction or "").strip().lower()
        if v in ("buy", "long"):
            return "long"
        if v in ("sell", "short"):
            return "short"
        return v

    @staticmethod
    def _extract_edge_pct(reason: str) -> Optional[float]:
        if not reason:
            return None
        m = _EDGE_REASON_RE.search(reason)
        if m is None:
            return None
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _move_pct(direction: str, entry_price: float, current_price: float) -> float:
        if entry_price <= 0:
            return 0.0
        if direction == "long":
            return ((current_price - entry_price) / entry_price) * 100.0
        return ((entry_price - current_price) / entry_price) * 100.0

    @staticmethod
    def _build_risk_policy(strategy_name: str, params: dict) -> PairRiskPolicy:
        def get_bool(key: str, default: bool) -> bool:
            value = params.get(key, default)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)

        def get_value(key: str, default, alias: Optional[str] = None):
            if alias is not None and alias in params:
                return params[alias]
            return params.get(key, default)

        def get_float(
            key: str,
            default: float,
            lo: float,
            hi: Optional[float] = None,
            alias: Optional[str] = None,
        ) -> float:
            raw = get_value(key, default, alias)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = default
            if hi is not None:
                value = min(hi, value)
            return max(lo, value)

        def get_int(key: str, default: int, lo: int, alias: Optional[str] = None) -> int:
            raw = get_value(key, default, alias)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
            return max(lo, value)

        # Enable by default for chronos hybrid, opt-in for others.
        default_enabled = strategy_name == "chronos_regime_hybrid"
        return PairRiskPolicy(
            enabled=get_bool("tail_risk_overlay_enabled", default_enabled),
            hard_stop_pct=get_float("hard_stop_pct", 0.35, 0.05, 10.0, alias="risk_hard_stop_pct"),
            trailing_activation_pct=get_float(
                "trailing_activation_pct",
                0.25,
                0.05,
                10.0,
                alias="risk_trailing_activation_pct",
            ),
            trailing_stop_pct=get_float(
                "trailing_stop_pct",
                0.18,
                0.05,
                10.0,
                alias="risk_trailing_stop_pct",
            ),
            time_stop_candles=get_int("time_stop_candles", 8, 1, alias="risk_time_stop_candles"),
            time_stop_edge_pct=get_float("time_stop_edge_pct", 0.03, 0.001, 5.0, alias="risk_time_stop_edge_pct"),
            degrade_after_losses=get_int("degrade_after_losses", 2, 1, alias="risk_degrade_after_losses"),
            pause_after_losses=get_int("pause_after_losses", 3, 1, alias="risk_pause_after_losses"),
            degrade_size_scale=get_float("degrade_size_scale", 0.5, 0.05, 1.0, alias="risk_degrade_size_scale"),
            pause_minutes=get_int("pause_minutes", 120, 1, alias="risk_pause_minutes"),
        )

    async def _record_close_outcome(
        self,
        *,
        pair: str,
        strategy_name: str,
        timeframe: str,
        risk_policy: PairRiskPolicy,
        risk_state: PairRiskState,
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Trade)
                .where(
                    Trade.source == "live",
                    Trade.pair == pair,
                    Trade.status == "closed",
                    Trade.pnl.is_not(None),
                )
                .order_by(Trade.exit_time.desc(), Trade.id.desc())
                .limit(1)
            )
            trade = result.scalar_one_or_none()

        if trade is None:
            return
        if risk_state.last_recorded_trade_id == trade.id:
            return

        risk_state.last_recorded_trade_id = trade.id
        pnl = float(trade.pnl or 0.0)
        prev_streak = risk_state.losing_streak
        prev_scale = risk_state.size_scale
        prev_cooldown = risk_state.cooldown_until

        if pnl < 0:
            risk_state.losing_streak += 1
        else:
            risk_state.losing_streak = 0
            risk_state.size_scale = 1.0
            risk_state.cooldown_until = None

        if not risk_policy.enabled:
            return

        now = datetime.now(timezone.utc)
        if pnl < 0 and risk_state.losing_streak >= risk_policy.pause_after_losses:
            risk_state.size_scale = min(risk_state.size_scale, risk_policy.degrade_size_scale)
            risk_state.cooldown_until = now + timedelta(minutes=risk_policy.pause_minutes)
            add_event(
                event="pair_paused_by_risk",
                level="warning",
                pair=pair,
                strategy=strategy_name,
                timeframe=timeframe,
                message="Pair paused after losing streak",
                details={
                    "streak_count": risk_state.losing_streak,
                    "pause_minutes": risk_policy.pause_minutes,
                    "resume_at": risk_state.cooldown_until.isoformat(),
                    "size_scale": risk_state.size_scale,
                    "latest_trade_id": trade.id,
                    "latest_trade_pnl": pnl,
                },
            )
        elif pnl < 0 and risk_state.losing_streak >= risk_policy.degrade_after_losses:
            risk_state.size_scale = risk_policy.degrade_size_scale
            add_event(
                event="losing_streak_degrade",
                level="warning",
                pair=pair,
                strategy=strategy_name,
                timeframe=timeframe,
                message="Position size scaled down after losing streak",
                details={
                    "streak_count": risk_state.losing_streak,
                    "size_scale": risk_state.size_scale,
                    "latest_trade_id": trade.id,
                    "latest_trade_pnl": pnl,
                },
            )
        elif pnl >= 0 and (
            prev_streak != risk_state.losing_streak
            or prev_scale != risk_state.size_scale
            or prev_cooldown is not None
        ):
            add_event(
                event="losing_streak_degrade",
                pair=pair,
                strategy=strategy_name,
                timeframe=timeframe,
                message="Losing streak controls reset after profitable close",
                details={
                    "streak_count": risk_state.losing_streak,
                    "size_scale": risk_state.size_scale,
                    "latest_trade_id": trade.id,
                    "latest_trade_pnl": pnl,
                },
            )

    @staticmethod
    def _reset_position_tracking(risk_state: PairRiskState) -> None:
        risk_state.tracked_direction = None
        risk_state.bars_held = 0
        risk_state.peak_price = None
        risk_state.trough_price = None
        risk_state.trailing_armed = False

    @staticmethod
    def _mark_position_open(
        risk_state: PairRiskState,
        *,
        direction: str,
        reference_price: float,
    ) -> None:
        risk_state.tracked_direction = direction
        risk_state.bars_held = 0
        risk_state.peak_price = reference_price
        risk_state.trough_price = reference_price
        risk_state.trailing_armed = False

    async def _close_with_risk_accounting(
        self,
        *,
        pair: str,
        strategy_name: str,
        timeframe: str,
        risk_policy: PairRiskPolicy,
        risk_state: PairRiskState,
        status: PairStatus,
        candle_ts: Optional[str] = None,
    ) -> bool:
        close_result = await self._order_manager.close_position(pair, strategy_name=strategy_name)
        if close_result is None:
            status.last_signal = "close_failed"
            status.last_updated = datetime.now(timezone.utc)
            add_event(
                event="risk_close_failed",
                level="error",
                pair=pair,
                strategy=strategy_name,
                timeframe=timeframe,
                message="Risk close attempt failed",
                details={"candle_ts": candle_ts},
            )
            return False

        await self._record_close_outcome(
            pair=pair,
            strategy_name=strategy_name,
            timeframe=timeframe,
            risk_policy=risk_policy,
            risk_state=risk_state,
        )
        self._reset_position_tracking(risk_state)
        if candle_ts is not None:
            status.last_candle_ts = candle_ts
        status.last_signal = "close"
        status.last_updated = datetime.now(timezone.utc)
        return True

    async def stop_all(self) -> None:
        pairs = list(self._pair_tasks.keys())
        for pair in pairs:
            await self.remove_pair(pair)
        logger.info("pair_manager_stopped_all", pair_count=len(pairs))

    async def _run_pair(self, pair: str, strategy: BaseStrategy, leverage: int, timeframe: str) -> None:
        status = self._pair_status[pair]
        log = logger.bind(pair=pair, strategy=strategy.name, timeframe=timeframe)

        await strategy.on_start()

        while True:
            try:
                await self._pair_loop_iteration(pair, strategy, leverage, timeframe, log)
                status.retry_count = 0
                status.error = None
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                log.info("pair_task_cancelled")
                add_event(
                    event="pair_task_cancelled",
                    pair=pair,
                    strategy=strategy.name,
                    timeframe=timeframe,
                    message="Pair task cancelled",
                )
                break

            except Exception as exc:
                status.retry_count += 1
                status.error = str(exc)
                log.error("pair_loop_error", error=str(exc), retry_count=status.retry_count)
                add_event(
                    event="pair_loop_error",
                    level="error",
                    pair=pair,
                    strategy=strategy.name,
                    timeframe=timeframe,
                    message=str(exc),
                    details={"retry_count": status.retry_count},
                )

                if status.retry_count > len(_RETRY_DELAYS):
                    log.critical("pair_max_retries_exceeded", retries=status.retry_count)
                    try:
                        await self._order_manager.close_position(pair, strategy_name=strategy.name)
                    except Exception as close_exc:
                        log.error("pair_emergency_close_failed", error=str(close_exc))
                    status.status = "failed"
                    status.last_updated = datetime.now(timezone.utc)
                    add_event(
                        event="pair_failed",
                        level="error",
                        pair=pair,
                        strategy=strategy.name,
                        timeframe=timeframe,
                        message="Max retries exceeded",
                    )
                    break

                delay = _RETRY_DELAYS[status.retry_count - 1]
                log.warning("pair_retry_backoff", delay=delay)
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break

        await strategy.on_stop()
        log.info("pair_task_exited", final_status=status.status)

    async def _pair_loop_iteration(
        self,
        pair: str,
        strategy: BaseStrategy,
        leverage: int,
        timeframe: str,
        log,
    ) -> None:
        status = self._pair_status[pair]
        risk_policy = self._pair_risk_policy.get(pair, PairRiskPolicy())
        risk_state = self._pair_risk_state.setdefault(pair, PairRiskState())
        now_utc = datetime.now(timezone.utc)

        if risk_policy.enabled and risk_state.cooldown_until is not None:
            if now_utc < risk_state.cooldown_until:
                remaining_sec = int((risk_state.cooldown_until - now_utc).total_seconds())
                status.last_signal = "hold"
                status.last_updated = now_utc
                log.info("pair_risk_pause_active", remaining_sec=remaining_sec)
                return
            risk_state.cooldown_until = None
            risk_state.losing_streak = 0
            risk_state.size_scale = 1.0

        raw_candles = await self._client.get_candles(
            pair,
            timeframe=timeframe,
            limit=max(strategy.lookback_period + 10, 50),
        )
        if not raw_candles:
            log.warning("pair_no_candles_received")
            return

        raw_candles = list(reversed(raw_candles))
        confirmed = [c for c in raw_candles if str(c.get("confirm", "1")) == "1"]
        if len(confirmed) < strategy.lookback_period + 1:
            log.warning("pair_insufficient_confirmed_candles", count=len(confirmed))
            return

        current = confirmed[-1]
        candle_ts = str(current.get("timestamp", ""))
        if status.last_candle_ts == candle_ts:
            log.debug("pair_skip_same_closed_candle", candle_ts=candle_ts)
            return
        history = confirmed[:-1]

        async with self._session_factory() as session:
            position = await repo.get_position(session, pair)

        sim_position: Optional[dict] = None
        current_close = float(current["close"])
        if position is not None:
            direction = self._normalize_direction(position.direction)
            if risk_state.tracked_direction != direction:
                risk_state.tracked_direction = direction
                risk_state.bars_held = 0
                risk_state.peak_price = current_close
                risk_state.trough_price = current_close
                risk_state.trailing_armed = False
            else:
                risk_state.bars_held += 1
                risk_state.peak_price = (
                    current_close
                    if risk_state.peak_price is None
                    else max(risk_state.peak_price, current_close)
                )
                risk_state.trough_price = (
                    current_close
                    if risk_state.trough_price is None
                    else min(risk_state.trough_price, current_close)
                )

            sim_position = {
                "direction": position.direction,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "unrealized_pnl": position.unrealized_pnl,
            }

            if risk_policy.enabled and direction in ("long", "short"):
                move_pct = self._move_pct(
                    direction=direction,
                    entry_price=float(position.entry_price),
                    current_price=current_close,
                )

                if move_pct <= -risk_policy.hard_stop_pct:
                    add_event(
                        event="risk_stop_triggered",
                        level="warning",
                        pair=pair,
                        strategy=strategy.name,
                        timeframe=timeframe,
                        message="Hard stop triggered",
                        details={
                            "direction": direction,
                            "entry_price": float(position.entry_price),
                            "trigger_price": current_close,
                            "move_pct": move_pct,
                            "threshold_pct": -risk_policy.hard_stop_pct,
                            "bars_held": risk_state.bars_held,
                        },
                    )
                    await self._close_with_risk_accounting(
                        pair=pair,
                        strategy_name=strategy.name,
                        timeframe=timeframe,
                        risk_policy=risk_policy,
                        risk_state=risk_state,
                        status=status,
                        candle_ts=candle_ts,
                    )
                    return

                if move_pct >= risk_policy.trailing_activation_pct:
                    risk_state.trailing_armed = True

                if risk_state.trailing_armed:
                    if direction == "long" and risk_state.peak_price is not None:
                        trail_trigger_price = risk_state.peak_price * (1.0 - (risk_policy.trailing_stop_pct / 100.0))
                        if current_close <= trail_trigger_price:
                            add_event(
                                event="trailing_stop_triggered",
                                level="warning",
                                pair=pair,
                                strategy=strategy.name,
                                timeframe=timeframe,
                                message="Trailing stop triggered",
                                details={
                                    "direction": direction,
                                    "entry_price": float(position.entry_price),
                                    "trigger_price": current_close,
                                    "peak_price": risk_state.peak_price,
                                    "trail_trigger_price": trail_trigger_price,
                                    "trailing_stop_pct": risk_policy.trailing_stop_pct,
                                    "bars_held": risk_state.bars_held,
                                },
                            )
                            await self._close_with_risk_accounting(
                                pair=pair,
                                strategy_name=strategy.name,
                                timeframe=timeframe,
                                risk_policy=risk_policy,
                                risk_state=risk_state,
                                status=status,
                                candle_ts=candle_ts,
                            )
                            return

                    if direction == "short" and risk_state.trough_price is not None:
                        trail_trigger_price = risk_state.trough_price * (1.0 + (risk_policy.trailing_stop_pct / 100.0))
                        if current_close >= trail_trigger_price:
                            add_event(
                                event="trailing_stop_triggered",
                                level="warning",
                                pair=pair,
                                strategy=strategy.name,
                                timeframe=timeframe,
                                message="Trailing stop triggered",
                                details={
                                    "direction": direction,
                                    "entry_price": float(position.entry_price),
                                    "trigger_price": current_close,
                                    "trough_price": risk_state.trough_price,
                                    "trail_trigger_price": trail_trigger_price,
                                    "trailing_stop_pct": risk_policy.trailing_stop_pct,
                                    "bars_held": risk_state.bars_held,
                                },
                            )
                            await self._close_with_risk_accounting(
                                pair=pair,
                                strategy_name=strategy.name,
                                timeframe=timeframe,
                                risk_policy=risk_policy,
                                risk_state=risk_state,
                                status=status,
                                candle_ts=candle_ts,
                            )
                            return
        else:
            self._reset_position_tracking(risk_state)

        # Fetch funding rate for context
        try:
            funding_rate = await self._client.get_funding_rate(pair)
        except Exception:
            funding_rate = None

        ctx = TradingContext(
            current_position=sim_position,
            account_balance=0.0,
            leverage=leverage,
            pair=pair,
            funding_rate=funding_rate,
        )

        signal: TradeSignal = await strategy.on_candle(current, history, ctx)

        if (
            sim_position is not None
            and risk_policy.enabled
            and signal.signal != Signal.CLOSE
            and risk_state.bars_held >= risk_policy.time_stop_candles
        ):
            edge_pct = self._extract_edge_pct(signal.reason)
            if edge_pct is not None and abs(edge_pct) <= risk_policy.time_stop_edge_pct:
                add_event(
                    event="time_stop_triggered",
                    level="warning",
                    pair=pair,
                    strategy=strategy.name,
                    timeframe=timeframe,
                    message="Time stop triggered on weak edge",
                    details={
                        "bars_held": risk_state.bars_held,
                        "edge_pct": edge_pct,
                        "edge_threshold_pct": risk_policy.time_stop_edge_pct,
                    },
                )
                signal = TradeSignal(
                    signal=Signal.CLOSE,
                    pair=pair,
                    reason=(
                        f"time_stop bars={risk_state.bars_held} "
                        f"edge={edge_pct:.3f}% threshold={risk_policy.time_stop_edge_pct:.3f}%"
                    ),
                )

        if signal.signal in (Signal.LONG, Signal.SHORT) and risk_policy.enabled and risk_state.size_scale < 1.0:
            scaled_size = max(1.0, min(100.0, signal.size_pct * risk_state.size_scale))
            signal.size_pct = scaled_size
            signal.reason = (
                f"{signal.reason} | losing_streak_scale={risk_state.size_scale:.2f}"
                if signal.reason
                else f"losing_streak_scale={risk_state.size_scale:.2f}"
            )

        status.last_candle_ts = candle_ts
        status.last_signal = signal.signal.value
        status.last_updated = datetime.now(timezone.utc)

        log.info("pair_signal", signal=signal.signal.value, reason=signal.reason)
        add_event(
            event="pair_signal",
            pair=pair,
            strategy=strategy.name,
            timeframe=timeframe,
            details={
                "signal": signal.signal.value,
                "reason": signal.reason,
            },
        )

        if signal.signal in (Signal.LONG, Signal.SHORT) and sim_position is None:
            result = await self._order_manager.open_position(pair, signal, strategy_name=strategy.name)
            if result is not None:
                self._mark_position_open(
                    risk_state,
                    direction="long" if signal.signal == Signal.LONG else "short",
                    reference_price=current_close,
                )
        elif signal.signal == Signal.CLOSE and sim_position is not None:
            result = await self._order_manager.close_position(pair, strategy_name=strategy.name)
            if result is not None:
                await self._record_close_outcome(
                    pair=pair,
                    strategy_name=strategy.name,
                    timeframe=timeframe,
                    risk_policy=risk_policy,
                    risk_state=risk_state,
                )
                self._reset_position_tracking(risk_state)
