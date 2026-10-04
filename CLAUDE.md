# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OKX crypto trading experiment rebuilt around a **safety-first** architecture. The promotion
gate is strict: `backtest → paper/demo trading → (only then) small live capital`.

**As of 2026-10-04 there are no strategies and no trading runner in the codebase.** Every
earlier strategy (Donchian breakout, MA ensemble, volatility breakout, BB+RSI) and the
paper/demo traders were removed to start strategy research from scratch; the snapshot is
preserved at git tag `archive/legacy-strategies-2026-10-04`. What remains is the
infrastructure a new strategy must plug into: the risk layer, exchange clients, research
data collectors, API, and the desktop/web UI. There is intentionally NO live-trading executor.

## Commands

### Run everything (bot + dashboard + Postgres)
```bash
docker compose up --build
```
- Bot API: http://localhost:8000 (OpenAPI at /docs)
- Dashboard: http://localhost:3000

### Desktop app (Tauri + React, primary UI)
```bash
cd desktop && npm run tauri:dev     # dev window with HMR (needs the bot API on :8000)
cd desktop && npx tsc --noEmit      # type check
```
Changing `tailwind.config.ts` requires restarting `tauri:dev`; Vite does not reload it.

### Bot tests (local venv at bot/.venv)
```bash
cd bot && .venv/bin/python -m pytest
```
Tests need no credentials or DB — `tests/conftest.py` injects dummy env vars.

### Dashboard (Next.js, secondary UI)
```bash
cd dashboard && npm run dev    # local dev
cd dashboard && npm run build  # production build + type check
```

### Database migrations
```bash
docker compose exec bot alembic upgrade head
```

## Architecture

### Safety layer (bot/app/core/) — every order must pass through this
- **`risk_gate.py`** — `RiskGate.validate(OrderIntent, AccountState)` checks order notional,
  price deviation (waived for reduce-only orders: flattening must never be refused),
  per-instrument/total exposure, daily loss (auto-trips kill switch), and order rate.
  `KillSwitch` is a JSON-file-persisted switch (survives restarts, fails closed on corrupt
  state; reduce-only orders are allowed while tripped).
- **`reconciliation.py`** — compares the bot's book against OKX positions; critical
  mismatches can trip the kill switch. Pure comparison + thin async runner.
- **`execution_quality.py`** — TCA: records decision price vs fill price per order to a
  JSONL log; separates strategy decay from bad execution.
- **`indicators.py`** — shared EMA/RSI/ATR/Bollinger helpers (pure, unit-tested) kept for
  future strategies.

### Research data (bot/scripts/)
- `collect_crowded_perp_snapshots.py`, `collect_basis_arbitrage_snapshots.py` — public-data
  collectors writing to `perp_market_snapshots` / `basis_arbitrage_snapshots`. Independent
  of any strategy. Existing data: one week of perp snapshots (2026-05-21..27, 42 instruments)
  and one day of basis snapshots — not enough for funding-carry conclusions yet.

### API (bot/app/api/)
- `routes_risk.py` — `/api/risk/status`, kill-switch trip/reset, reconciliation, TCA summary
- `routes_trading.py` — runtime logs (`/api/trading/logs`), health, Telegram test
- `routes_trades.py` — trades/pnl/orders/positions (sources: `live`, `paper`, `demo`)
- `routes_markets.py` — top-100 USDT-SWAP tickers with OKX coin icons

### Exchange layer (bot/app/exchange/)
- `okx_client.py` — authenticated OKX v5 REST (HMAC, rate limiting, demo/live header)
- `public_market_data.py` — credential-free public endpoints (candles, tickers, funding,
  instruments) for collectors and future backtests

### Desktop (desktop/src/) — Toss-Securities-style design system
- `styles/globals.css` holds every color as a CSS token; `:root[data-theme="dark"]` flips the
  theme. `lib/theme.tsx` persists system/light/dark. Price direction follows the KR
  convention: up = red, down = blue. `components/ui.tsx` is the shared kit.
- Pages: Home, Markets, Trades, Settings (left side menu: trading / theme / logs).

## Conventions

- **Never bypass the RiskGate**: any new runner that places (real or simulated) orders must
  validate intents through `RiskGate`, record fills in `ExecutionQualityLog`, and reconcile
  against the exchange.
- Strategy modules must stay pure (no I/O) so they are unit-testable; runners do I/O.
- A new strategy ships with: a look-ahead-free, fee-aware backtest (decision at close t,
  fill at open t+1), a buy-and-hold benchmark on the same window, and pass criteria written
  down *before* the first paper run.
- State files live under `bot/state/` (gitignored): kill switch, TCA log.
- Any demo runner must refuse to start when `OKX_MODE != demo`. Promotion to live is a human
  decision backed by paper/demo evidence, not a config flip.
- Research context: `docs/research/trading-bot-feature-landscape-2026.md` documents the
  feature landscape survey and gap analysis that drove this architecture.

## Environment

Copy `.env.example` to `.env`. `OKX_MODE=demo` uses OKX simulated trading. Risk limits
(`RISK_MAX_*`, `MAX_DAILY_LOSS_USD`) are enforced by the risk gate at runtime.
