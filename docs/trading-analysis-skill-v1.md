# Trading Analysis Skill v1 (in-process)

## Endpoint

`POST /api/analysis/skill/run`

Runs in-process candidate experiment, backtest, and recommendation flow.
No internal HTTP self-calls are used.

## Request contract

```json
{
  "strategy_name": "example_rsi",
  "baseline_strategy_name": "example_rsi",
  "pair": "ETH-USDT-SWAP",
  "timeframe": "1H",
  "windows": [
    {"name": "train",   "start": "2026-03-01T00:00:00", "end": "2026-03-05T00:00:00"},
    {"name": "val",     "start": "2026-03-05T00:00:00", "end": "2026-03-08T00:00:00"},
    {"name": "holdout", "start": "2026-03-08T00:00:00", "end": "2026-03-10T00:00:00"}
  ],
  "assumptions": {
    "initial_balance": 10000,
    "leverage": 3,
    "fee_rate": 0.0005,
    "slippage_pct": 0.05,
    "funding_rate_per_8h": 0.0001,
    "cooldown_candles": 1,
    "liquidity_impact_factor": 0.1,
    "maintenance_margin_ratio": 0.005,
    "liquidation_fee_pct": 0.002
  },
  "search_space": {
    "rsi_period": [7, 21],
    "oversold": [20, 40],
    "overbought": [60, 80]
  },
  "top_k": 3,
  "run_limits": {
    "max_combinations": 100,
    "timeout_sec": 900,
    "retry_per_failed_job": 1,
    "partial_failure_threshold": 0.20
  }
}
```

### Canonical metrics + alias policy

- Internal canonical keys: `total_pnl`, `sharpe_ratio`, `max_drawdown`, `win_rate`, `trade_count`
- API boundary aliases accepted and normalized: `sharpe`→`sharpe_ratio`, `mdd`→`max_drawdown`
- Storage/scoring must never rely on alias keys.

### Run-risk controls

- `max_combinations`: default 100, hard cap 500
- `timeout_sec`: default 900, hard cap 1800
- `retry_per_failed_job`: default 1, max 2
- `partial_failure_threshold`: default 0.20
- Failure ratio = `failed_combinations / attempted_combinations`
- If `failure_ratio > threshold`: status `failed`, `degraded_mode=true`
- If failures exist and ratio within threshold: status `warning`, `degraded_mode=true`
- If no failures: status `ok`, `degraded_mode=false`

### Replay rule (top-1)

Replay passes only when all are true:

1. `abs(replay.total_pnl - original.total_pnl) / max(abs(original.total_pnl), 1.0) <= 0.05`
2. `abs(replay.sharpe_ratio - original.sharpe_ratio) <= 0.15`
3. `replay.trade_count >= 0.90 * original.trade_count`

### Response shape

Response includes:

- `run_id`
- `status` (`ok|warning|failed`)
- `recommendation_count`
- `baseline.metrics_by_window` (train/val/holdout)
- `recommendations[rank, params, metrics_by_window, baseline_delta_by_window, replay_pass, replay_delta]`
- `failures {failed_combinations, failure_ratio, degraded_mode}`

### Non-goals

- No live deploy automation
- No strategy source generation/editing
