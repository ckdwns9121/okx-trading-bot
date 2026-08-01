# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OKX crypto trading experiment rebuilt around a **safety-first** architecture. The previous
strategy set was deleted after failing its own cost-adjusted validation; the current system
runs a daily MA-ensemble trend-following strategy through a strict promotion gate:
`backtest → paper/demo trading → (only then) small live capital`. There is intentionally
NO live-trading executor in the codebase.

## Commands

### Run everything (bot + dashboard + Postgres)
```bash
docker compose up --build
```
- Bot API: http://localhost:8000 (OpenAPI at /docs)
- Dashboard: http://localhost:3000

### Bot tests (local venv at bot/.venv)
```bash
cd bot && .venv/bin/python -m pytest
```
Tests need no credentials or DB — `tests/conftest.py` injects dummy env vars.

### Dashboard
```bash
cd dashboard && npm run dev    # local dev
cd dashboard && npm run build  # production build + type check
```

### Strategy runners (inside bot/ with .env loaded, or via docker compose exec)
```bash
python -m scripts.run_trend_following_paper_trader --backtest   # cost-aware backtest on real OKX data
python -m scripts.run_trend_following_paper_trader              # internal paper loop (no orders sent)
python -m scripts.run_trend_following_demo_trader --once        # one pass against OKX demo account
python -m scripts.run_trend_following_demo_trader               # hourly demo loop (refuses unless OKX_MODE=demo)
```

### Database migrations
```bash
docker compose exec bot alembic upgrade head
```

## Architecture

### Safety layer (bot/app/core/) — every order must pass through this
- **`risk_gate.py`** — `RiskGate.validate(OrderIntent, AccountState)` checks order notional,
  price deviation, per-instrument/total exposure, daily loss (auto-trips kill switch), and
  order rate. `KillSwitch` is a JSON-file-persisted switch (survives restarts, fails closed
  on corrupt state; reduce-only orders are allowed while tripped).
- **`reconciliation.py`** — compares the bot's book against OKX positions; critical
  mismatches can trip the kill switch. Pure comparison + thin async runner.
- **`execution_quality.py`** — TCA: records decision price vs fill price per order to a
  JSONL log; separates strategy decay from bad execution.

### Strategy (bot/app/core/trend_following.py)
Pure logic: SMA ensemble signal (default 20/50/100d) → target exposure fraction
(votes/total, long/flat only), rebalance planning, paper book, and a look-ahead-free
backtest (decision at close t, fill at open t+1, fees included).

### Runners (bot/scripts/)
- `run_trend_following_paper_trader.py` — internal simulation on spot pairs; also hosts
  shared helpers (candle pagination with confirmed-only filter, state persistence).
- `run_trend_following_demo_trader.py` — real orders to OKX demo (SWAP, 1x, long/flat).
  Auto-detects account position mode (net vs long/short → posSide handling). Exchange is
  the source of truth for position size; reconciles every loop.
- `collect_crowded_perp_snapshots.py`, `collect_basis_arbitrage_snapshots.py` — research
  data collectors (kept independent of any strategy).

### API (bot/app/api/)
- `routes_risk.py` — `/api/risk/status`, kill-switch trip/reset, reconciliation, TCA summary
- `routes_paper.py` — `/api/paper/trend-following` (paper book state)
- `routes_trading.py` — runtime logs (`/api/trading/logs`), health, Telegram test
- `routes_trades.py`, `routes_markets.py` — trades/positions/markets

### Exchange layer (bot/app/exchange/)
- `okx_client.py` — authenticated OKX v5 REST (HMAC, rate limiting, demo/live header)
- `public_market_data.py` — credential-free public endpoints (candles, tickers, funding,
  instruments) used by research collectors and strategy runners

### Dashboard (dashboard/src/)
- `app/config/page.tsx` — risk card (kill-switch status + emergency stop button), runtime
  logs, health. `lib/api.ts` / `lib/types.ts` hold the typed API client.

## Conventions

- **Never bypass the RiskGate**: any new runner that places (real or simulated) orders must
  validate intents through `RiskGate`, record fills in `ExecutionQualityLog`, and reconcile
  against the exchange.
- Strategy modules must stay pure (no I/O) so they are unit-testable; runners do I/O.
- State files live under `bot/state/` (gitignored): kill switch, TCA log, trader state.
- Demo runner must refuse to start when `OKX_MODE != demo`. Promotion to live is a human
  decision backed by paper/demo evidence, not a config flip.
- Research context: `docs/research/trading-bot-feature-landscape-2026.md` documents the
  feature landscape survey and gap analysis that drove this architecture.

## Environment

Copy `.env.example` to `.env`. `OKX_MODE=demo` uses OKX simulated trading. Risk limits
(`RISK_MAX_*`, `MAX_DAILY_LOSS_USD`) are enforced by the risk gate at runtime.
