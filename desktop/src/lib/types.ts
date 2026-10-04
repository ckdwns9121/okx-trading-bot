export type TradeSource = "live" | "paper";

export interface Trade {
  id: number;
  strategy_name: string;
  pair: string;
  direction: "long" | "short" | string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  leverage: number;
  pnl: number | null;
  pnl_pct: number | null;
  fee: number;
  entry_time: string;
  exit_time: string | null;
  status: "open" | "closed" | "cancelled" | string;
  source: TradeSource | string;
}

export interface Position {
  id: number;
  pair: string;
  direction: "long" | "short" | string;
  entry_price: number;
  quantity: number;
  leverage: number;
  unrealized_pnl: number;
  exchange_position_id?: string | null;
  opened_at: string;
}

export interface PnlSummary {
  realized_pnl: number;
  win_rate: number;
  trade_count: number;
  today_pnl: number;
}

export interface AccountBalance {
  total_equity: number;
  usdt_equity: number;
  usdt_available: number;
  updated_at_ms?: string | null;
}

export interface TradingLogEvent {
  id: number;
  timestamp: string;
  level: "info" | "warning" | "error" | string;
  event: string;
  pair?: string | null;
  strategy?: string | null;
  timeframe?: string | null;
  message?: string | null;
  details?: Record<string, unknown>;
}

export interface HealthStatus {
  db: "ok" | "error" | string;
  okx_api: {
    status: "ok" | "error" | string;
    mode: "live" | "demo" | string;
  };
  trading_tasks: {
    active: number;
    failed: number;
    stopped: number;
  };
  circuit_breaker: "removed" | string;
}

export interface KillSwitchState {
  tripped: boolean;
  reason?: string | null;
  source?: string | null;
  changed_at?: string | null;
}

export interface RiskStatus {
  kill_switch: KillSwitchState;
  limits: Record<string, number>;
  kill_switch_file: string;
  execution_log_file: string;
}

/* ---------------- demo trader ---------------- */

export interface DemoTraderConfig {
  strategy: "ma" | "donchian" | string;
  pairs: string[];
  allocation_usd: number;
  leverage: number;
  poll_seconds: number;
  min_trade_usd: number;
  ma_periods: number[];
  donchian: {
    entry_period: number;
    exit_period: number;
    atr_period: number;
    atr_stop_mult: number | null;
  };
  mode: "demo" | "live" | string;
}

export interface DemoTrade {
  inst_id: string;
  side: "buy" | "sell" | string;
  contracts: string;
  price: number;
  notional_usd: number;
  fee_usd: number;
  realized_pnl_usd: number | null;
  decision_price: number;
  target_fraction: number;
  occurred_at: string;
  cl_ord_id: string;
}

export interface DemoTraderStatus {
  running: boolean;
  status: "running" | "stale" | "not_started" | string;
  message?: string;
  strategy?: string | null;
  started_at?: string | null;
  last_loop_at?: string | null;
  age_seconds?: number | null;
  stale_after_seconds?: number;
  config?: DemoTraderConfig | null;
  pairs?: string[];
  processed_candle_ts?: Record<string, string>;
  positions?: Record<string, { contracts: string; avg_entry_price: number }>;
  trade_count?: number;
  realized_pnl_usd?: number;
  fees_paid_usd?: number;
  recent_trades?: DemoTrade[];
}

/* ---------------- backtest ---------------- */

export interface BacktestRequest {
  strategy: "donchian" | "ma";
  pairs: string[];
  days: number;
  allocation_usd: number;
  fee_pct: number;
  min_trade_usd: number;
  donchian: {
    entry_period: number;
    exit_period: number;
    atr_period: number;
    atr_stop_mult: number;
  };
  ma_periods: number[];
}

export interface EquityPoint {
  ts: string;
  equity: number;
  buy_hold?: number;
}

export interface BacktestResult {
  strategy: string;
  params?: Record<string, unknown>;
  instruments: string[];
  days_tested: number;
  starting_equity_usd: number;
  final_equity_usd: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  trade_count: number;
  win_rate_pct?: number;
  fees_paid_usd: number;
  buy_hold_return_pct: number;
  buy_hold_max_drawdown_pct: number;
  equity_curve: EquityPoint[];
  request: BacktestRequest;
  candles_from: string;
  candles_to: string;
}

export interface MarketTicker {
  pair: string;
  symbol: string;
  name: string;
  price: number;
  change_24h: number;
  change_pct_24h: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
  icon_url: string;
  sector: string;
}
