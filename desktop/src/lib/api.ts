import type {
  AccountBalance,
  BacktestRequest,
  BacktestResult,
  DemoTraderStatus,
  HealthStatus,
  KillSwitchState,
  MarketTicker,
  PnlSummary,
  Position,
  RiskStatus,
  TradingLogEvent,
  Trade,
  TradeSource,
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.toString() || "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
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
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `?${qs}` : "";
}

export async function getPnl(source: TradeSource = "live"): Promise<PnlSummary> {
  return fetchJson<PnlSummary>(`/api/pnl${buildQuery({ source })}`);
}

export async function getPositions(): Promise<Position[]> {
  return fetchJson<Position[]>("/api/positions");
}

export interface TradeQueryParams {
  [key: string]: string | number | boolean | undefined | null;
  source?: TradeSource;
  pair?: string;
  strategy?: string;
  limit?: number;
}

export async function getTrades(params: TradeQueryParams = {}): Promise<Trade[]> {
  return fetchJson<Trade[]>(`/api/trades${buildQuery(params)}`);
}

export async function getHealth(): Promise<HealthStatus> {
  return fetchJson<HealthStatus>("/api/health");
}

export async function getAccountBalance(): Promise<AccountBalance> {
  return fetchJson<AccountBalance>("/api/account/balance");
}

export async function getTradingLogs(limit = 120): Promise<TradingLogEvent[]> {
  const data = await fetchJson<{ items: TradingLogEvent[] }>(
    `/api/trading/logs${buildQuery({ limit })}`,
  );
  return data.items ?? [];
}

export async function getMarkets(): Promise<MarketTicker[]> {
  return fetchJson<MarketTicker[]>("/api/markets");
}

export async function getRiskStatus(): Promise<RiskStatus> {
  return fetchJson<RiskStatus>("/api/risk/status");
}

export async function tripKillSwitch(reason: string): Promise<KillSwitchState> {
  return fetchJson<KillSwitchState>("/api/risk/kill-switch/trip", {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function resetKillSwitch(): Promise<KillSwitchState> {
  return fetchJson<KillSwitchState>("/api/risk/kill-switch/reset", {
    method: "POST",
  });
}

export async function getDemoTrader(): Promise<DemoTraderStatus> {
  return fetchJson<DemoTraderStatus>("/api/paper/demo-trader");
}

/** 백테스트는 캔들을 받아오느라 수 초 걸린다. 호출 측에서 로딩 상태를 보여줄 것. */
export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  return fetchJson<BacktestResult>("/api/backtest/run", {
    method: "POST",
    body: JSON.stringify(req),
  });
}
