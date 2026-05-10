import type {
  BacktestParams,
  BacktestRunWithTrades,
  CompareResult,
  AccountBalance,
  HealthStatus,
  MarketTicker,
  MonteCarloResult,
  OptimizationResult,
  PairStatus,
  ValidationProgress,
  ValidationResult,
  ParamSpace,
  PnlSummary,
  Position,
  SelectionResult,
  StrategyConfig,
  StrategyInfo,
  TradingLogEvent,
  Trade,
  TradeAnalytics,
} from "./types";

const isServer = typeof window === "undefined";
const API_BASE = isServer
  ? (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
  : "http://localhost:8000";

async function fetchJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status} ${path}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function buildQuery(
  params: { [key: string]: string | number | boolean | undefined | null },
): string {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(
      ([k, v]) =>
        `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`,
    )
    .join("&");
  return qs ? `?${qs}` : "";
}

// ── PnL ─────────────────────────────────────────────────────────────────────

export async function getPnl(
  source: "live" | "paper" | "backtest" = "live",
): Promise<PnlSummary> {
  return fetchJson<PnlSummary>(`/api/pnl${buildQuery({ source })}`);
}

// ── Positions ────────────────────────────────────────────────────────────────

export async function getPositions(): Promise<Position[]> {
  return fetchJson<Position[]>("/api/positions");
}

// ── Trades ───────────────────────────────────────────────────────────────────

export interface TradeQueryParams {
  [key: string]: string | number | boolean | undefined | null;
  source?: "live" | "paper" | "backtest";
  pair?: string;
  strategy?: string;
  limit?: number;
}

export async function getTrades(
  params: TradeQueryParams = {},
): Promise<Trade[]> {
  return fetchJson<Trade[]>(`/api/trades${buildQuery(params)}`);
}

// ── Health ───────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<HealthStatus> {
  return fetchJson<HealthStatus>("/api/health");
}

export async function getAccountBalance(): Promise<AccountBalance> {
  return fetchJson<AccountBalance>("/api/account/balance");
}

// ── Trading control ──────────────────────────────────────────────────────────

export async function startTrading(): Promise<void> {
  await fetchJson<unknown>("/api/trading/start", { method: "POST" });
}

export async function stopTrading(): Promise<void> {
  await fetchJson<unknown>("/api/trading/stop", { method: "POST" });
}

export async function getTradingStatus(): Promise<PairStatus[]> {
  const data = await fetchJson<{
    running: boolean;
    pairs: Array<{
      pair: string;
      state: string;
      strategy: string;
      timeframe?: string | null;
      error?: string | null;
    }>;
  }>("/api/trading/status");
  return (data.pairs ?? []).map((p) => {
    const normalizedState =
      p.state === "failed"
        ? "error"
        : p.state === "running" ||
            p.state === "stopped" ||
            p.state === "error" ||
            p.state === "idle"
          ? p.state
          : "unknown";
    return {
    pair: p.pair,
    strategy_name: p.strategy || "",
    timeframe: p.timeframe ?? null,
    status: normalizedState as PairStatus["status"],
    error: p.error ?? null,
  };
  });
}

export async function getTradingLogs(limit = 120): Promise<TradingLogEvent[]> {
  const data = await fetchJson<{ items: TradingLogEvent[] }>(
    `/api/trading/logs${buildQuery({ limit })}`,
  );
  return data.items ?? [];
}

// ── Backtest ─────────────────────────────────────────────────────────────────

export async function runBacktest(
  params: BacktestParams,
): Promise<BacktestRunWithTrades> {
  const submit = await fetchJson<{ run_id: string; status: string }>("/api/backtest", {
    method: "POST",
    body: JSON.stringify(params),
  });
  // API runs synchronously now, so result is ready immediately
  return fetchJson<BacktestRunWithTrades>(`/api/backtest/${submit.run_id}`);
}

export async function getBacktestAnalytics(id: string): Promise<TradeAnalytics> {
  return fetchJson<TradeAnalytics>(`/api/backtest/${id}/analytics`);
}

export async function runMonteCarlo(id: string): Promise<MonteCarloResult> {
  return fetchJson<MonteCarloResult>(`/api/backtest/${id}/monte-carlo`, { method: "POST" });
}

// ── Markets ──────────────────────────────────────────────────────────────────

export async function getMarkets(): Promise<MarketTicker[]> {
  return fetchJson<MarketTicker[]>("/api/markets");
}

// ── Strategies & Config ──────────────────────────────────────────────────────

export async function getStrategies(): Promise<string[]> {
  const data = await fetchJson<{ strategies: string[] }>("/api/config/strategies");
  return data.strategies;
}

export async function getConfig(): Promise<StrategyConfig[]> {
  const rows = await fetchJson<Array<{
    id: number;
    strategy_name: string;
    pair: string;
    timeframe: string;
    parameters_json: Record<string, unknown> | null;
    leverage: number;
    is_active: boolean;
  }>>("/api/config");

  return rows.map((r) => ({
    id: r.id,
    strategy_name: r.strategy_name,
    pair: r.pair,
    timeframe: r.timeframe || "1m",
    leverage: r.leverage,
    enabled: r.is_active,
    params: r.parameters_json ?? {},
  }));
}

export async function upsertSingleConfig(
  config: {
    strategy_name: string;
    pair: string;
    timeframe?: string;
    parameters_json?: Record<string, unknown> | null;
    leverage?: number;
    is_active?: boolean;
  },
): Promise<void> {
  await fetchJson<unknown>("/api/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

// ── Optimizer ─────────────────────────────────────────────────────────────

export async function runOptimization(params: {
  strategy_name: string;
  pair: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance: number;
  leverage: number;
  n_iterations?: number;
  walk_forward_split?: number;
  objective?: string;
}): Promise<OptimizationResult> {
  return fetchJson<OptimizationResult>("/api/optimize", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function getParamSpace(strategy: string): Promise<ParamSpace> {
  return fetchJson<ParamSpace>(`/api/optimize/param-space/${strategy}`);
}

// ── Compare ──────────────────────────────────────────────────────────────────

export async function runComparison(params: {
  strategies: string[];
  pairs: string[];
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance: number;
  leverage: number;
}): Promise<CompareResult[]> {
  return fetchJson<CompareResult[]>("/api/compare", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function getStrategyInfos(): Promise<StrategyInfo[]> {
  return fetchJson<StrategyInfo[]>("/api/compare/strategies");
}

// ── Validation ──────────────────────────────────────────────────────────────

export async function runValidation(params?: {
  pairs?: string[];
  timeframes?: string[];
  initial_balance?: number;
  leverage?: number;
  lookback_days?: number;
  top_n?: number;
  n_iterations?: number;
}): Promise<{ run_id: string; status: string }> {
  return fetchJson("/api/validate/run", {
    method: "POST",
    body: JSON.stringify(params ?? {}),
  });
}

export async function getValidationProgress(): Promise<ValidationProgress> {
  return fetchJson<ValidationProgress>("/api/validate/progress");
}

export async function getValidationResults(): Promise<ValidationResult | null> {
  return fetchJson<ValidationResult | null>("/api/validate/results");
}

export async function deployToDemo(
  strategyName: string,
): Promise<{ status: string; message: string }> {
  return fetchJson(`/api/validate/deploy/${encodeURIComponent(strategyName)}`, {
    method: "POST",
  });
}

export async function cancelValidation(): Promise<{
  cancelled: boolean;
  message: string;
}> {
  return fetchJson("/api/validate/cancel", { method: "DELETE" });
}

// ── Selector ─────────────────────────────────────────────────────────────────

export async function getRecommendation(params: {
  pair: string;
  timeframe?: string;
  lookback_days?: number;
  initial_balance?: number;
  leverage?: number;
}): Promise<SelectionResult> {
  return fetchJson<SelectionResult>("/api/selector/recommend", {
    method: "POST",
    body: JSON.stringify(params),
  });
}
