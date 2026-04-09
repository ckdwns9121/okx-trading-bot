export interface Trade {
  id: number;
  strategy_name: string;
  pair: string;
  direction: "long" | "short";
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  leverage: number;
  pnl: number | null;
  pnl_pct: number | null;
  fee: number;
  entry_time: string;
  exit_time: string | null;
  status: "open" | "closed" | "cancelled";
  source: "live" | "backtest" | "paper";
}

export interface Order {
  id: number;
  pair: string;
  side: "buy" | "sell";
  order_type: "market" | "limit" | "stop" | "stop_limit";
  price: number | null;
  quantity: number;
  leverage: number;
  status: "pending" | "filled" | "partial" | "cancelled" | "rejected";
  exchange_order_id: string | null;
  cl_ord_id: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: number;
  pair: string;
  direction: "long" | "short";
  entry_price: number;
  quantity: number;
  leverage: number;
  unrealized_pnl: number;
  opened_at: string;
}

export interface BacktestRun {
  id: string;
  strategy_name: string;
  pair: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance: number;
  leverage: number;
  fee_rate: number;
  slippage_pct: number;
  total_pnl: number;
  win_rate: number;
  max_drawdown: number;
  sharpe_ratio: number | null;
  trade_count: number;
  created_at: string;
}

export interface TradeAnalytics {
  profit_factor: number | null;
  avg_win: number;
  avg_loss: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_hold_time_minutes: number;
  best_trade_pnl: number;
  worst_trade_pnl: number;
  expectancy: number;
  payoff_ratio: number | null;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
}

export interface MonteCarloResult {
  median_final_balance: number;
  p5_final_balance: number;
  p95_final_balance: number;
  median_max_drawdown: number;
  p95_max_drawdown: number;
  ruin_probability: number;
  n_simulations: number;
}

export interface EquityCurvePoint {
  index: number;
  balance: number;
  drawdown: number;
}

export interface SensitivityResult {
  fee_rate: number;
  slippage_pct: number;
  total_pnl: number;
  sharpe_ratio: number;
  win_rate: number;
  trade_count: number;
  final_balance: number;
}

export interface BacktestRunWithTrades extends BacktestRun {
  trades: Trade[];
  equity_curve: EquityCurvePoint[];
  buy_hold_pnl: number | null;
  buy_hold_return_pct: number | null;
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

export interface PairStatus {
  pair: string;
  strategy_name: string;
  timeframe?: string | null;
  status: "running" | "stopped" | "error" | "idle" | "unknown";
  leverage?: number;
  retry_count?: number;
  last_signal?: string | null;
  error?: string | null;
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
  db: "ok" | "error";
  okx_api: {
    status: "ok" | "error";
    mode: "live" | "demo";
  };
  okx_ws: "connected" | "disconnected" | "error";
  trading_tasks: {
    active: number;
    failed: number;
    stopped: number;
  };
  circuit_breaker: "open" | "closed" | "half_open";
}

export interface StrategyConfig {
  id?: number;
  strategy_name: string;
  pair: string;
  timeframe: string;
  leverage: number;
  enabled: boolean;
  params: Record<string, unknown>;
}

export interface BacktestParams {
  strategy_name: string;
  pair: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance?: number;
  leverage?: number;
  fee_rate?: number;
  slippage_pct?: number;
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

export interface TrialResult {
  trial_number: number;
  params: Record<string, number>;
  train_sharpe: number;
  train_pnl: number;
  train_win_rate: number;
  val_sharpe: number;
  val_pnl: number;
  val_win_rate: number;
  score: number;
}

export interface OptimizationResult {
  strategy_name: string;
  pair: string;
  best_params: Record<string, number>;
  best_score: number;
  total_trials: number;
  trials: TrialResult[];
  train_period: string;
  val_period: string;
}

export interface ParamSpace {
  [param: string]: [number, number];
}

export interface CompareResult {
  strategy: string;
  pair: string;
  total_pnl: number;
  win_rate: number;
  max_drawdown: number;
  sharpe_ratio: number;
  trade_count: number;
  profit_factor: number;
}

export interface StrategyInfo {
  name: string;
  description: string;
}

export interface RegimeResult {
  regime: string;
  confidence: number;
  adx: number;
  volatility: number;
  trend_direction: number;
  details: Record<string, number>;
}

export interface StrategyScore {
  strategy_name: string;
  sharpe_ratio: number;
  total_pnl: number;
  win_rate: number;
  regime_fit: number;
  composite_score: number;
}

// ── Validation ──────────────────────────────────────────────────────────────

export interface StrategyRanking {
  rank: number;
  strategy_name: string;
  pair: string;
  timeframe: string;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_pnl: number;
  trade_count: number;
  composite_score: number;
}

export interface OptimizedStrategy {
  strategy_name: string;
  original_params: Record<string, number>;
  optimized_params: Record<string, number>;
  before_score: number;
  after_score: number;
}

export interface ValidationProgress {
  run_id: string;
  phase: "idle" | "collecting" | "backtesting" | "ranking" | "optimizing" | "complete" | "error" | "cancelled";
  pct: number;
  message: string;
  started_at: string | null;
}

export interface ValidationResult {
  run_id: string;
  rankings: StrategyRanking[];
  optimized: OptimizedStrategy[];
  completed_at: string;
  total_backtests: number;
  duration_seconds: number;
}

export interface SelectionResult {
  pair: string;
  regime: RegimeResult;
  recommended_strategy: string;
  recommended_params: Record<string, number>;
  scores: StrategyScore[];
  reasoning: string;
}
