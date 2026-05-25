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

export interface FundingOiDemoStatus {
  running: boolean;
  stale: boolean;
  status: "running" | "stale" | "stopped" | "not_started" | string;
  strategy_name: string;
  mode?: "live" | "demo" | string | null;
  dry_run?: boolean | null;
  started_at?: string | null;
  last_loop_at?: string | null;
  latest_event_at?: string | null;
  snapshot_count_seen?: number | null;
  open_position?: Record<string, unknown> | null;
  closed_trade_count: number;
  processed_event_count: number;
  order_error_count: number;
  close_error_count: number;
  reconciliation_count: number;
  reconciliation_error_count: number;
  watched_instrument_count: number;
  watched_instruments: string[];
  config: Record<string, unknown>;
  message?: string | null;
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

export interface MarketDislocationRow {
  inst_id: string;
  observed_at: string;
  age_seconds: number;
  price: number;
  lookback_return_pct: number | null;
  funding_rate: number | null;
  oi_change_pct: number | null;
  spread_pct: number;
  book_imbalance: number;
  trade_imbalance: number;
  price_flush_score: number;
  funding_heat_score: number;
  oi_buildup_score: number;
  spread_quality_score: number;
  flow_imbalance_score: number;
  book_imbalance_score: number;
  dislocation_score: number;
  candidate_side: string;
  readiness: "ready" | "watch" | "cold" | string;
  signal_ready: boolean;
  reason: string;
}

export interface MarketDislocationResponse {
  strategy_name: string;
  generated_at: string;
  lookback_seconds: number;
  fresh_seconds: number;
  item_count: number;
  ready_count: number;
  items: MarketDislocationRow[];
}

export interface BasisArbitrageRow {
  inst_id: string;
  spot_inst_id: string;
  observed_at: string;
  age_seconds: number;
  perp_mid_price: number;
  spot_mid_price: number;
  basis_pct: number;
  funding_rate: number | null;
  funding_8h_pct: number | null;
  estimated_daily_funding_pct: number | null;
  perp_spread_pct: number;
  spot_spread_pct: number;
  estimated_round_trip_cost_pct: number;
  net_funding_8h_after_cost_pct: number | null;
  candidate_side: string;
  carry_score: number;
  readiness: "ready" | "watch" | "cold" | string;
  signal_ready: boolean;
  reason: string;
}

export interface BasisArbitrageResponse {
  strategy_name: string;
  generated_at: string;
  fresh_seconds: number;
  item_count: number;
  ready_count: number;
  items: BasisArbitrageRow[];
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
