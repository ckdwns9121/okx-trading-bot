# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Async crypto futures trading bot for OKX exchange with backtesting, strategy optimization, and a Next.js dashboard. Runs entirely via Docker Compose (bot + dashboard + Postgres).

## Commands

### Run everything (dev mode with hot-reload)
```bash
docker compose up --build
```
- Bot API: http://localhost:8000
- Dashboard: http://localhost:3000

### Database migrations
```bash
# Inside bot container
docker compose exec bot alembic upgrade head
docker compose exec bot alembic revision --autogenerate -m "description"
```

### Bot tests
```bash
cd bot && pip install -e ".[dev]" && pytest
```

### Dashboard
```bash
cd dashboard && npm install && npm run dev   # local dev
cd dashboard && npm run build                # production build
cd dashboard && npm run lint                 # eslint
```

## Architecture

### Two-service monorepo

- **`bot/`** — Python 3.12 FastAPI backend (uvicorn, async). Handles OKX API interaction, strategy execution, backtesting, optimization.
- **`dashboard/`** — Next.js 15 / React 19 / TypeScript frontend. Talks to bot API via `dashboard/src/lib/api.ts`.
- **Postgres 16** — trade/backtest persistence via SQLAlchemy async + Alembic.

### Bot internals (`bot/app/`)

- **`app/main.py`** — FastAPI app factory with lifespan. Initializes OKXClient, strategy registry, circuit breaker, and live engine. Components are lazily imported so the API starts even if modules are missing.
- **`app/config.py`** — `pydantic-settings` config from `.env`. Key settings: `OKX_MODE` (demo/live), `DATABASE_URL`, risk limits.
- **`app/exchange/okx_client.py`** — Async OKX REST API v5 wrapper with HMAC signing and rate limiting (20 req/2s). Uses `httpx`.
- **`app/exchange/okx_websocket.py`** — WebSocket client for real-time data.
- **`app/core/strategy_base.py`** — `BaseStrategy` ABC. Strategies must implement `on_candle()`, `lookback_period`, and `configure()`. Signals: LONG/SHORT/CLOSE/HOLD.
- **`app/core/strategy_registry.py`** — Singleton registry with `auto_discover()` that scans `bot/strategies/` for `BaseStrategy` subclasses at startup.
- **`app/core/backtest_engine.py`** — Backtesting engine.
- **`app/core/live_engine.py`** — Live/paper trading loop.
- **`app/core/circuit_breaker.py`** — Risk management: daily loss limits.
- **`app/core/optimizer.py`** — Strategy parameter optimization.
- **`app/core/strategy_selector.py`** — Regime-aware strategy recommendation.
- **`app/db/`** — SQLAlchemy async engine, session factory, repository pattern.
- **`app/models/`** — ORM models: Trade, Order, Position, BacktestRun, Candle, StrategyConfig.
- **`app/api/`** — FastAPI routers: backtest, trading, trades, config, markets, optimizer, compare, selector.

### Strategy pattern (`bot/strategies/`)

Strategies are Python files auto-discovered at startup. Each defines a class inheriting `BaseStrategy` with:
- `name` class attribute (used as registry key)
- `lookback_period` property (number of historical candles needed)
- `on_candle(candle, history, context) -> TradeSignal`
- `configure(params)` for parameter overrides

### Dashboard (`dashboard/src/`)

- **`src/lib/api.ts`** — Typed API client; uses `API_URL` env var server-side, `localhost:8000` client-side.
- **`src/lib/types.ts`** — Shared TypeScript type definitions.
- **`src/app/`** — Next.js App Router pages: overview, backtest, trades, config, markets, optimize, compare, selector.
- **`src/components/`** — Recharts-based charts (PnlChart, WinRateCard) and data tables.

## Environment

Copy `.env.example` to `.env` and fill in OKX API credentials. `OKX_MODE=demo` uses simulated trading (no real funds).
