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

export interface Order {
  id: string;
  pair: string;
  side: "buy" | "sell" | string;
  order_type: "market" | "limit" | "stop" | "stop_limit" | string;
  price: number | null;
  quantity: number;
  leverage: number;
  status: "pending" | "filled" | "partial" | "cancelled" | "rejected" | string;
  exchange_order_id: string | null;
  cl_ord_id: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
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
