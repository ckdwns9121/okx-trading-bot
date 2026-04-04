"""Multi-pair orchestration with per-pair asyncio task supervision."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.order_manager import OrderManager
from app.core.runtime_events import add_event
from app.core.strategy_base import BaseStrategy, Signal, TradingContext, TradeSignal
from app.core.strategy_registry import StrategyRegistry
from app.db import repository as repo
from app.exchange.okx_client import OKXClient
from app.logging_config import get_logger

logger = get_logger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (10.0, 30.0, 60.0)
_POLL_INTERVAL_SECONDS: float = 60.0


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

        self._pair_status[pair] = PairStatus(
            pair=pair,
            strategy_name=strategy_name,
            timeframe=timeframe,
            status="running",
            leverage=leverage,
        )

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
            details={"leverage": leverage, "params": params or {}},
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
            await self._order_manager.close_position(pair)

        self._pair_tasks.pop(pair, None)
        if pair in self._pair_status:
            self._pair_status[pair].status = "stopped"
            self._pair_status[pair].last_updated = datetime.now(timezone.utc)

        logger.info("pair_removed", pair=pair)
        add_event(event="pair_removed", pair=pair, message="Pair task stopped")

    def get_status(self) -> dict[str, dict]:
        return {
            pair: {
                "strategy_name": s.strategy_name, "status": s.status,
                "timeframe": s.timeframe,
                "leverage": s.leverage, "retry_count": s.retry_count,
                "last_candle_ts": s.last_candle_ts,
                "last_signal": s.last_signal, "error": s.error,
                "last_updated": s.last_updated.isoformat(),
            }
            for pair, s in self._pair_status.items()
        }

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
                        await self._order_manager.close_position(pair)
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
        if position is not None:
            sim_position = {
                "direction": position.direction,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "unrealized_pnl": position.unrealized_pnl,
            }

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
            await self._order_manager.open_position(pair, signal)
        elif signal.signal == Signal.CLOSE and sim_position is not None:
            await self._order_manager.close_position(pair)
