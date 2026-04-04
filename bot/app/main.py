"""FastAPI application entry point for the OKX trading bot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import get_logger, setup_logging

# Initialise logging before any other app code runs.
setup_logging()
logger = get_logger(__name__)

_VERSION = "1.0.0"
_STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ------------------------------------------------------------------ #
    # Startup
    # ------------------------------------------------------------------ #
    logger.info(
        "bot_starting",
        version=_VERSION,
        mode=settings.OKX_MODE,
        strategies_dir=str(_STRATEGIES_DIR),
    )

    # 1. OKX REST client
    from app.exchange.okx_client import OKXClient

    okx_client = OKXClient(
        api_key=settings.OKX_API_KEY,
        secret=settings.OKX_SECRET,
        passphrase=settings.OKX_PASSPHRASE,
        mode=settings.OKX_MODE,
    )
    app.state.okx_client = okx_client
    logger.info("okx_client_initialised", mode=settings.OKX_MODE)

    # 2. Strategy registry + auto-discover
    from app.core.strategy_registry import auto_discover, registry

    if _STRATEGIES_DIR.is_dir():
        try:
            auto_discover(_STRATEGIES_DIR)
            logger.info(
                "strategies_discovered",
                count=len(registry.list_all()),
                names=registry.list_all(),
            )
        except Exception as exc:
            logger.warning("strategy_discovery_failed", error=str(exc))
    else:
        logger.warning("strategies_dir_missing", path=str(_STRATEGIES_DIR))

    app.state.strategy_registry = registry

    # 3. Optional core components — imported lazily so the API still starts
    #    even when the parallel modules are not yet committed.
    live_engine = None
    circuit_breaker = None
    telegram_notifier = None

    try:
        from app.core.telegram_notifier import TelegramNotifier

        telegram_notifier = TelegramNotifier(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            enabled=settings.TELEGRAM_NOTIFICATIONS_ENABLED,
        )
        app.state.telegram_notifier = telegram_notifier
        logger.info("telegram_notifier_initialised", enabled=telegram_notifier.enabled)
    except ImportError:
        logger.warning("telegram_notifier_unavailable")
        app.state.telegram_notifier = None

    try:
        from app.core.circuit_breaker import CircuitBreaker
        from app.db.database import AsyncSessionLocal

        circuit_breaker = CircuitBreaker(
            session_factory=AsyncSessionLocal,
            max_daily_loss=settings.MAX_DAILY_LOSS_USD,
        )
        app.state.circuit_breaker = circuit_breaker
        logger.info("circuit_breaker_initialised", max_daily_loss=settings.MAX_DAILY_LOSS_USD)
    except ImportError:
        logger.warning("circuit_breaker_unavailable")
        app.state.circuit_breaker = None

    try:
        from app.core.live_engine import LiveEngine

        live_engine = LiveEngine(
            okx_client=okx_client,
            strategy_registry=registry,
            circuit_breaker=circuit_breaker,
            telegram_notifier=telegram_notifier,
        )
        app.state.live_engine = live_engine
        logger.info("live_engine_initialised")
    except ImportError:
        logger.warning("live_engine_unavailable")
        app.state.live_engine = None

    logger.info("bot_started", version=_VERSION, mode=settings.OKX_MODE)

    # ------------------------------------------------------------------ #
    # Hand control to the application
    # ------------------------------------------------------------------ #
    yield

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    logger.info("bot_shutting_down")

    if live_engine is not None:
        try:
            is_running = getattr(live_engine, "is_running", False)
            if is_running:
                await live_engine.stop()
                logger.info("live_engine_stopped")
        except Exception as exc:
            logger.error("live_engine_stop_error", error=str(exc))

    try:
        await okx_client.close()
        logger.info("okx_client_closed")
    except Exception as exc:
        logger.error("okx_client_close_error", error=str(exc))

    if telegram_notifier is not None:
        try:
            await telegram_notifier.close()
            logger.info("telegram_notifier_closed")
        except Exception as exc:
            logger.error("telegram_notifier_close_error", error=str(exc))

    logger.info("bot_shutdown_complete", version=_VERSION)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="OKX Trading Bot",
        version=_VERSION,
        description="Async crypto futures trading bot with backtesting support.",
        lifespan=lifespan,
    )

    # CORS — allow all origins for local / container development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    from app.api.routes_backtest import router as backtest_router
    from app.api.routes_compare import router as compare_router
    from app.api.routes_config import router as config_router
    from app.api.routes_markets import router as markets_router
    from app.api.routes_optimizer import router as optimizer_router
    from app.api.routes_trades import router as trades_router
    from app.api.routes_trading import router as trading_router
    from app.api.routes_selector import router as selector_router
    from app.api.routes_validate import router as validate_router

    app.include_router(backtest_router)
    app.include_router(trading_router)
    app.include_router(trades_router)
    app.include_router(config_router)
    app.include_router(markets_router)
    app.include_router(optimizer_router)
    app.include_router(compare_router)
    app.include_router(selector_router)
    app.include_router(validate_router)

    # Root endpoint
    @app.get("/", tags=["meta"], summary="Bot identity")
    async def root() -> dict[str, str]:
        return {
            "name": "OKX Trading Bot",
            "version": _VERSION,
            "mode": settings.OKX_MODE,
        }

    return app


app = create_app()
