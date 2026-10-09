export type TradeSource = "demo" | "live" | "paper";

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

export interface TraderSleeve {
  inst: string;
  cash_usd: number;
  qty: number;
  entry_px: number | null;
  entry_ts: number | null;
  realized_pnl_usd: number;
}

export interface TraderTrade {
  inst: string;
  side: "buy" | "sell" | string;
  reason: string;
  bar_ts: number;
  fill_ts: number;
  decision_close: number;
  avg_px: number;
  base_qty: number;
  quote_usd: number;
  fee_usd: number;
  realized_pnl_usd: number | null;
}

export interface DonchianTraderStatus {
  status: "running" | "stale" | "not_started" | string;
  strategy?: string;
  started_at?: string;
  last_loop_at?: string;
  age_seconds?: number | null;
  config?: { pairs: string[]; capital_usd: number; poll_seconds: number; mode: string; params: Record<string, unknown> };
  sleeves?: Record<string, TraderSleeve>;
  handled_bar?: Record<string, number>;
  pending_orders?: number;
  trade_count?: number;
  realized_pnl_usd?: number;
  fees_usd?: number;
  recent_trades?: TraderTrade[];
  equity_history?: { day: string; equity_usd: number }[];
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
