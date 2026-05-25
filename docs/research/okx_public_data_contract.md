# OKX Public Data Contract Notes

Verified against official OKX API v5 docs on 2026-05-21. OKX docs are live,
not pinned to a versioned release. Preserve raw string fields in selected
`raw_json` fragments because numeric values are returned as strings and fields
can be added without a versioned migration note.

Regional domain note: OKX documents regional API domains. The default project
domain remains `www.okx.com`, but accounts registered for US/AU/EU regions may
need their regional API host.

## Market Trades: Recent

- Endpoint: `GET /api/v5/market/trades`
- Auth: public
- Rate limit: 100 requests / 2s, rule: IP
- Params: `instId` required; `limit` optional, max 500, default 100
- Scope: recent public transactions for one instrument
- Response fields: `instId`, `tradeId`, `px`, `sz`, `side`, `source`, `ts`
- Units: `sz` is contracts for `FUTURES` / `SWAP` / `OPTION`
- `side`: OKX documents this as taker trade side, `buy` or `sell`. The pipeline
  still preserves raw values and uses the name
  `exchange_reported_trade_side_imbalance` unless promotion evidence explicitly
  justifies stronger wording.
- `source`: `0` normal order, `1` Enhanced Liquidity Program order

## Market Trades: History

- Endpoint: `GET /api/v5/market/history-trades`
- Auth: public
- Rate limit: 20 requests / 2s, rule: IP
- Scope: recent transactions from the last 3 months with pagination
- Params: `instId` required; `type` optional (`1` tradeId default,
  `2` timestamp); `after`; `before`; `limit` max/default 100
- Response fields and units match recent trades.

## Order Book

- Endpoint: `GET /api/v5/market/books`
- Auth: public
- Rate limit: 40 requests / 2s, rule: IP
- Params: `instId` required; `sz` optional, max 400 per side, default 1
- Response fields: `asks`, `bids`, `ts`, `seqId`
- Each book level is `[price, quantity, deprecated, order_count]`
- Quantity unit is contracts for derivatives

## Ticker

- Endpoint: `GET /api/v5/market/ticker`
- Auth: public
- Rate limit: 20 requests / 2s, rule: IP
- Params: `instId` required
- Response fields include `instType`, `instId`, `last`, `lastSz`, `askPx`,
  `askSz`, `bidPx`, `bidSz`, 24h volume fields, and `ts`

## Funding Rate

- Endpoint: `GET /api/v5/public/funding-rate`
- Auth: public
- Rate limit: 10 requests / 2s, rule: IP + instrument ID
- Params: `instId` required
- Response fields include `instType`, `instId`, `method`, `formulaType`,
  `fundingRate`, `nextFundingRate`, `fundingTime`, `nextFundingTime`,
  `minFundingRate`, `maxFundingRate`, `interestRate`, `impactValue`,
  `settState`, `settFundingRate`, `premium`, `ts`
- Semantics: positive rates mean longs pay shorts at `fundingTime`; negative
  rates mean shorts pay longs.
- Live public responses can include `prevFundingTime`; treat it as optional.

## Funding Rate History

- Endpoint: `GET /api/v5/public/funding-rate-history`
- Auth: public
- Rate limit: 10 requests / 2s, rule: IP + instrument ID
- Scope: up to 3 months
- Params: `instId` required; `before`; `after`; `limit` max/default 400
- Response fields: `instType`, `instId`, `formulaType`, `fundingRate`,
  `realizedRate`, `fundingTime`, `method`

## Open Interest: Current

- Endpoint: `GET /api/v5/public/open-interest`
- Auth: public
- Rate limit: 20 requests / 2s, rule: IP + instrument ID
- Params: `instType` required; `instId` optional for futures/swap/option/events
- Response fields: `instType`, `instId`, `oi`, `oiCcy`, `oiUsd`, `ts`
- Units: `oi` contracts, `oiCcy` coin/crypto, `oiUsd` USD

## Open Interest: Contract History

- Endpoint: `GET /api/v5/rubik/stat/contracts/open-interest-history`
- Section: Trading Statistics, official OKX docs
- Auth: public
- Rate limit: 10 requests / 2s, rule: IP + instrument ID
- Scope: futures and perps; latest 1,440 entries
- Params: `instId` required; `period` optional default `5m`; `begin`; `end`;
  `limit` max/default 100
- Response array order: `[ts, oi, oiCcy, oiUsd]`
- Caveat: official historical range wording is ambiguous for older backtests;
  verify availability before assuming long-range history.

## Taker Volume: Aggregate

- Endpoint: `GET /api/v5/rubik/stat/taker-volume`
- Section: Trading Statistics, official OKX docs
- Auth: public
- Rate limit: 5 requests / 2s, rule: IP
- Params: `ccy` required; `instType` required (`SPOT`, `CONTRACTS`); `begin`;
  `end`; `period` default `5m`
- Response array order: `[ts, sellVol, buyVol]`
- Caveat: docs title says taker volume, while field descriptions say sell/buy
  volume. Preserve raw.

## Taker Volume: Contract

- Endpoint: `GET /api/v5/rubik/stat/taker-volume-contract`
- Section: Trading Statistics, official OKX docs
- Auth: public
- Rate limit: 5 requests / 2s, rule: IP + instrument ID
- Scope: futures and perps; latest 1,440 entries
- Params: `instId` required; `period` optional default `5m`; `unit` optional
  default `1`; `begin`; `end`; `limit` max/default 100
- Response array order: `[ts, sellVol, buyVol]`

## Phase 1a Live Sample Protocol

- Instruments: `BTC-USDT-SWAP`, `ETH-USDT-SWAP`, `SOL-USDT-SWAP`
- Duration: 30 minutes
- Polling cadence: 10 seconds
- Required checks:
  - At least 99% source timestamp parse rate.
  - Per-endpoint timestamps are nondecreasing, except documented order quirks.
  - `observed_at - source_ts` p95 is at most 5 seconds where source timestamps
    exist.
  - Missing required normalized fields remain below 1%.
  - No sustained HTTP 429/5xx; collector backoff and data gaps are recorded.

## Official Sources

- OKX API docs: https://www.okx.com/docs-v5/en/
- OKX API landing page: https://www.okx.com/en-us/okx-api

