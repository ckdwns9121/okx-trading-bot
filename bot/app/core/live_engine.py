"""Live trading engine: composes all core components and drives the bot."""

from app.config import settings as app_settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.order_manager import OrderManager
from app.core.pair_manager import PairManager
from app.core.reconciler import Reconciler
from app.core.runtime_events import add_event
from app.core.strategy_registry import StrategyRegistry
from app.db import repository as repo
from app.db.database import AsyncSessionLocal
from app.exchange.okx_client import OKXClient
from app.logging_config import get_logger

logger = get_logger(__name__)


class LiveEngine:
    """Top-level coordinator for the live trading bot."""

    def __init__(
        self,
        okx_client: OKXClient,
        strategy_registry: StrategyRegistry,
        circuit_breaker: CircuitBreaker,
        telegram_notifier=None,
    ) -> None:
        self._client = okx_client
        self.strategy_registry = strategy_registry
        self.circuit_breaker = circuit_breaker
        self._telegram_notifier = telegram_notifier
        self.is_running = False

        self.order_manager = OrderManager(
            okx_client=okx_client,
            session_factory=AsyncSessionLocal,
            circuit_breaker=self.circuit_breaker,
            settings=app_settings,
            telegram_notifier=self._telegram_notifier,
        )

        self.reconciler = Reconciler(
            okx_client=okx_client,
            session_factory=AsyncSessionLocal,
        )

        self.pair_manager = PairManager(
            okx_client=okx_client,
            session_factory=AsyncSessionLocal,
            order_manager=self.order_manager,
            strategy_registry=strategy_registry,
        )

    async def start(self) -> None:
        log = logger.bind(mode=app_settings.OKX_MODE)
        log.info("live_engine_starting")
        add_event(event="engine_starting", message="Live engine starting")

        try:
            summary = await self.reconciler.reconcile()
            log.info("live_engine_reconciliation_done", **summary)
        except Exception as exc:
            log.error("live_engine_reconciliation_error", error=str(exc))

        try:
            async with AsyncSessionLocal() as session:
                active_configs = await repo.get_active_configs(session)
        except Exception as exc:
            log.error("live_engine_load_configs_error", error=str(exc))
            active_configs = []

        if not active_configs:
            log.warning("live_engine_no_active_configs")

        for config in active_configs:
            strategy_name = config.strategy_name
            pair = config.pair
            leverage = config.leverage
            timeframe = getattr(config, "timeframe", "1m")
            params = config.parameters_json or {}

            try:
                self.strategy_registry.get(strategy_name)
            except KeyError:
                log.error(
                    "live_engine_strategy_not_registered",
                    strategy=strategy_name,
                    pair=pair,
                )
                continue

            try:
                await self.pair_manager.add_pair(
                    pair=pair,
                    strategy_name=strategy_name,
                    leverage=leverage,
                    timeframe=timeframe,
                    params=params,
                )
                log.info(
                    "live_engine_pair_started",
                    pair=pair,
                    strategy=strategy_name,
                    leverage=leverage,
                    timeframe=timeframe,
                )
                add_event(
                    event="engine_pair_started",
                    pair=pair,
                    strategy=strategy_name,
                    timeframe=timeframe,
                    details={"leverage": leverage, "params": params},
                )
            except Exception as exc:
                log.error(
                    "live_engine_add_pair_error",
                    pair=pair,
                    strategy=strategy_name,
                    timeframe=timeframe,
                    error=str(exc),
                )
                add_event(
                    event="engine_pair_start_error",
                    level="error",
                    pair=pair,
                    strategy=strategy_name,
                    timeframe=timeframe,
                    message=str(exc),
                )

        self.is_running = True
        log.info(
            "live_engine_started",
            active_pairs=len(self.pair_manager.get_status()),
        )
        add_event(
            event="engine_started",
            details={"active_pairs": len(self.pair_manager.get_status())},
            message="Live engine started",
        )

    async def stop(self) -> None:
        log = logger.bind(mode=app_settings.OKX_MODE)
        log.info("live_engine_stopping")
        add_event(event="engine_stopping", message="Live engine stopping")

        status_snapshot = self.pair_manager.get_status()

        try:
            await self.pair_manager.stop_all()
        except Exception as exc:
            log.error("live_engine_stop_all_error", error=str(exc))

        self.is_running = False
        log.info(
            "live_engine_stopped",
            pairs_stopped=len(status_snapshot),
            circuit_breaker_tripped=self.circuit_breaker.is_tripped,
        )
        add_event(
            event="engine_stopped",
            details={
                "pairs_stopped": len(status_snapshot),
                "circuit_breaker_tripped": self.circuit_breaker.is_tripped,
            },
            message="Live engine stopped",
        )

    def get_status(self) -> dict:
        return {
            "circuit_breaker": {
                "tripped": self.circuit_breaker.is_tripped,
                "max_daily_loss_usd": app_settings.MAX_DAILY_LOSS_USD,
            },
            "pairs": self.pair_manager.get_status(),
            "mode": app_settings.OKX_MODE,
        }
