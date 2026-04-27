# ICT Liquidity Sweep + MSS + FVG Strategy

`ict_liquidity_fvg` is a deterministic, backtest-first interpretation of a narrow ICT setup. It is not a full discretionary ICT model and does not guarantee profitability.

## Model

Bullish sequence:

1. A closed candle sweeps below the recent `sweep_lookback` low.
2. The same candle closes back above that swept low.
3. Within `mss_max_bars`, a later candle closes above the recent `mss_lookback` swing high.
4. A bullish fair value gap forms: candle `-3` high is below candle `-1` low.
5. Within `retest_max_bars`, price retests that FVG.
6. The strategy emits `LONG`, with stop below the sweep low and take-profit by `reward_risk`.

Bearish setups mirror the same logic above recent highs.

## Quality filters

The base ICT sequence can be made stricter with optional filters:

- `trend_filter_mode: "ema"` — long only above EMA, short only below EMA.
- `session_filter_mode: "utc"` — enter only inside `session_start_hour_utc` to `session_end_hour_utc`.
- `min_atr_pct` / `max_atr_pct` — skip dead or overheated volatility regimes.
- `min_mss_body_pct` and `min_mss_displacement_pct` — require stronger MSS candles.
- `retest_confirmation: "directional_close"` — long retests must close bullish; short retests must close bearish.

## Parameters

```json
{
  "direction_mode": "both",
  "sweep_lookback": 20,
  "mss_lookback": 5,
  "mss_max_bars": 10,
  "fvg_max_bars": 10,
  "retest_max_bars": 10,
  "min_sweep_pct": 0.0,
  "min_fvg_pct": 0.02,
  "sl_buffer_pct": 0.03,
  "reward_risk": 2.0,
  "size_pct": 10.0,
  "cooldown_bars": 3,
  "trend_filter_mode": "off",
  "trend_lookback": 96,
  "min_trend_slope_pct": 0.0,
  "session_filter_mode": "off",
  "session_start_hour_utc": 7,
  "session_end_hour_utc": 20,
  "atr_period": 14,
  "min_atr_pct": 0.0,
  "max_atr_pct": 100.0,
  "min_mss_body_pct": 0.0,
  "min_mss_displacement_pct": 0.0,
  "retest_confirmation": "off"
}
```

Research profile that reduced losses in the 2026-03-01 to 2026-04-25 validation run:

```json
{
  "session_filter_mode": "utc",
  "session_start_hour_utc": 7,
  "session_end_hour_utc": 20,
  "reward_risk": 1.5
}
```

This profile is still not approved for live trading; see `docs/ict-liquidity-fvg-improvement-report.md`.

## Safe rollout

1. Run unit tests.
2. Backtest on BTC/ETH with realistic fee, slippage, funding, and liquidation assumptions.
3. Compare several timeframes and parameter sets.
4. Only after stable backtests, test OKX demo mode.
5. Keep live trading opt-in and small; this strategy should never be enabled with real money by default.

Example backtest body excerpt:

```json
{
  "strategy_name": "ict_liquidity_fvg",
  "pair": "BTC-USDT-SWAP",
  "timeframe": "15m",
  "initial_balance": 10000,
  "leverage": 2,
  "parameters_json": {
    "direction_mode": "both",
    "sweep_lookback": 20,
    "reward_risk": 2.0,
    "size_pct": 10
  }
}
```
