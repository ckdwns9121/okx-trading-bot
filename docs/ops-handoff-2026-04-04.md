# Ops Handoff — 2026-04-04

This document summarizes the production-relevant work completed in this cycle.

## 1) Live engine/runtime improvements

- Added per-pair timeframe configuration (`strategy_configs.timeframe`) and migration `002`.
- Live pair loop now evaluates **confirmed closed candles only** and deduplicates by `last_candle_ts`.
- Fixed order reconciliation lookup by passing `instId` when querying order by `clOrdId`.

## 2) Observability

- Added runtime event buffer and endpoint: `GET /api/trading/logs`.
- Config dashboard now displays a live log panel with auto-refresh.
- Added account balance panel to overview.

## 3) Execution accounting

- Open position records now use fill-aware entry price/size when available.
- Close path switched to explicit market close order flow with fill lookup.
- Trade records now include calculated `exit_price`, `pnl`, `pnl_pct` using contract value.

## 4) Telegram integration

- Trade notifications for open/close/reject/error events.
- Command poller supports:
  - `/help`, `/status`, `/position(s)`, `/balance`, `/pnl`, `/logs`
  - `/start`, `/stop`, `/close <PAIR>`
- Added test endpoint: `POST /api/trading/telegram/test`.

### Required env

```env
TELEGRAM_NOTIFICATIONS_ENABLED=true
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<chat_id>
TELEGRAM_COMMANDS_ENABLED=true
TELEGRAM_POLL_TIMEOUT_SEC=25
```

## 5) Local docker override fix

- `docker-compose.override.yml` now explicitly includes `env_file: .env` for `bot`.
- This prevents silent Telegram disablement in local reload mode.

## 6) Strategy scan results (full compare run)

Run scope: 12 strategies × 2 pairs × 3 TF × 2 windows (30d/90d) = 144 runs.

Top robust cluster:

1. `example_rsi` — `ETH-USDT-SWAP`, `1H`, 90d
   - PnL: `+45,331.64`
   - Sharpe: `4.9501`
   - Profit factor: `3.0913`
   - Win rate: `56.79%`
   - Max DD: `8.69%`

2. `rsi_bollinger_combo` — `ETH-USDT-SWAP`, `1H`, 90d
   - PnL: `+28,299.11`
   - Sharpe: `5.7399`
   - Profit factor: `3.9906`
   - Win rate: `59.62%`
   - Max DD: `9.13%`

3. `mean_reversion` — `ETH-USDT-SWAP`, `1H`, 90d
   - PnL: `+19,699.87`
   - Sharpe: `4.4108`
   - Profit factor: `2.6963`
   - Win rate: `55.74%`
   - Max DD: `11.84%`

Current user preference was set to **profit-max priority**, so live recommendation is `example_rsi` on `ETH 1H`.
