"""FastAPI application entry point for the OKX trading bot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import get_logger, setup_logging

# Initialise logging before any other app code runs.
setup_logging()
logger = get_logger(__name__)

_VERSION = "1.0.0"
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

    # 1.5 Runtime event persistence (DB)
    try:
        from app.core.runtime_events import configure_persistence
        from app.db.database import AsyncSessionLocal

        configure_persistence(session_factory=AsyncSessionLocal)
        logger.info("runtime_event_persistence_initialised")
    except Exception as exc:
        logger.warning("runtime_event_persistence_unavailable", error=str(exc))

    # 2. Optional integrations.
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

    logger.info("bot_started", version=_VERSION, mode=settings.OKX_MODE)

    # ------------------------------------------------------------------ #
    # Hand control to the application
    # ------------------------------------------------------------------ #
    yield

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    logger.info("bot_shutting_down")

    try:
        from app.core.runtime_events import shutdown_persistence

        await shutdown_persistence()
    except Exception as exc:
        logger.error("runtime_event_persistence_stop_error", error=str(exc))

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
        description="Async crypto futures trading bot for Funding/OI demo execution.",
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
    from app.api.routes_markets import router as markets_router
    from app.api.routes_risk import router as risk_router
    from app.api.routes_trades import router as trades_router
    from app.api.routes_trading import router as trading_router

    app.include_router(trading_router)
    app.include_router(trades_router)
    app.include_router(markets_router)
    app.include_router(risk_router)

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
