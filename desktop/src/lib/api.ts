import type {
  AccountBalance,
  BasisArbitrageResponse,
  FundingOiDemoStatus,
  HealthStatus,
  MarketDislocationResponse,
  MarketTicker,
  PnlSummary,
  Position,
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

export async function getFundingOiDemoStatus(): Promise<FundingOiDemoStatus> {
  return fetchJson<FundingOiDemoStatus>("/api/trading/funding-oi-demo/status");
}

export async function getMarketDislocation(): Promise<MarketDislocationResponse> {
  return fetchJson<MarketDislocationResponse>("/api/trading/market-dislocation");
}

export async function getBasisArbitrage(): Promise<BasisArbitrageResponse> {
  return fetchJson<BasisArbitrageResponse>("/api/trading/basis-arbitrage");
}

export async function getMarkets(): Promise<MarketTicker[]> {
  return fetchJson<MarketTicker[]>("/api/markets");
}
