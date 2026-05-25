"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getBasisArbitrage,
  getFundingOiDemoStatus,
  getHealth,
  getMarketDislocation,
  getTradingLogs,
} from "@/lib/api";
import type {
  BasisArbitrageResponse,
  BasisArbitrageRow,
  FundingOiDemoStatus,
  HealthStatus,
  MarketDislocationResponse,
  MarketDislocationRow,
  TradingLogEvent,
} from "@/lib/types";

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function ConfigPage() {
  const [demoStatus, setDemoStatus] = useState<FundingOiDemoStatus | null>(null);
  const [dislocation, setDislocation] = useState<MarketDislocationResponse | null>(null);
  const [basisArbitrage, setBasisArbitrage] = useState<BasisArbitrageResponse | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [logs, setLogs] = useState<TradingLogEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const [h, lg, demo, market, basis] = await Promise.allSettled([
      getHealth(),
      getTradingLogs(120),
      getFundingOiDemoStatus(),
      getMarketDislocation(),
      getBasisArbitrage(),
    ]);
    if (h.status === "fulfilled") setHealth(h.value);
    if (lg.status === "fulfilled") setLogs(lg.value);
    if (demo.status === "fulfilled") setDemoStatus(demo.value);
    if (market.status === "fulfilled") setDislocation(market.value);
    if (basis.status === "fulfilled") setBasisArbitrage(basis.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const [nextLogs, nextDemoStatus, nextMarket, nextBasis] = await Promise.all([
          getTradingLogs(120),
          getFundingOiDemoStatus(),
          getMarketDislocation(),
          getBasisArbitrage(),
        ]);
        setLogs(nextLogs);
        setDemoStatus(nextDemoStatus);
        setDislocation(nextMarket);
        setBasisArbitrage(nextBasis);
      } catch {
        // Keep the current dashboard state on transient API errors.
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  const mode = health?.okx_api.mode ?? null;
  const demoConfig = demoStatus?.config ?? {};
  const demoOpenPosition = demoStatus?.open_position ?? null;
  const demoLeverage = Number(demoConfig["leverage"] ?? 0);
  const demoNotional = Number(demoConfig["notional_usd"] ?? 0);
  const demoMargin = Number(demoConfig["effective_margin_usd"] ?? 0);

  function renderLogText(log: TradingLogEvent): string {
    if (typeof log.message === "string" && log.message.trim().length > 0) {
      return log.message;
    }
    if (log.details && Object.keys(log.details).length > 0) {
      return JSON.stringify(log.details);
    }
    return "-";
  }

  function renderTime(value?: string | null): string {
    if (!value) return "-";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "-";
    return dt.toLocaleString("ko-KR");
  }

  function renderUsd(value: number): string {
    if (!Number.isFinite(value) || value <= 0) return "-";
    return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }

  function renderPct(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return "-";
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
  }

  function renderFunding(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return "-";
    return `${(value * 100).toFixed(4)}%`;
  }

  function ScoreBar({ value }: { value: number }) {
    const pct = Math.max(0, Math.min(100, value * 100));
    const color = value >= 0.7 ? "bg-red-400" : value >= 0.55 ? "bg-amber-300" : "bg-slate-500";
    return (
      <div className="h-2 w-20 rounded bg-slate-800">
        <div className={`h-2 rounded ${color}`} style={{ width: `${pct}%` }} />
      </div>
    );
  }

  function readinessClass(row: MarketDislocationRow): string {
    if (row.signal_ready) return "border-red-500/40 bg-red-500/10 text-red-200";
    if (row.readiness === "watch") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    return "border-slate-700 bg-slate-900/50 text-slate-400";
  }

  function readinessLabel(row: MarketDislocationRow): string {
    if (row.signal_ready) return "진입 가능";
    if (row.readiness === "watch") return "관찰 중";
    return "대기";
  }

  function basisReadinessClass(row: BasisArbitrageRow): string {
    if (row.signal_ready) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
    if (row.readiness === "watch") return "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";
    return "border-slate-700 bg-slate-900/50 text-slate-400";
  }

  function basisReadinessLabel(row: BasisArbitrageRow): string {
    if (row.signal_ready) return "차익 후보";
    if (row.readiness === "watch") return "관찰 중";
    return "대기";
  }

  function basisSideLabel(value: string): string {
    if (value === "long_spot_short_perp") return "현물 롱 / 선물 숏";
    if (value === "long_perp_short_spot") return "선물 롱 / 현물 숏";
    return "없음";
  }

  function reasonLabel(reason: string): string {
    const labels: Record<string, string> = {
      "snapshot stale": "시장 데이터가 오래됨",
      "not enough price history": "가격 이력이 부족함",
      "drop not large enough": "가격 하락 폭이 부족함",
      "funding missing": "펀딩비 데이터 없음",
      "funding not crowded long": "롱 포지션 쏠림이 약함",
      "OI history missing": "미결제약정 이력이 부족함",
      "OI buildup not enough": "미결제약정 증가가 부족함",
      "spread too wide": "스프레드가 너무 넓음",
      "long flush reversal candidate": "롱 청산 후 반등 후보",
    };
    return reason
      .split(", ")
      .map((item) => labels[item] ?? item)
      .join(", ");
  }

  function strategyLabel(value?: string | null): string {
    if (value === "Funding + OI Flush Reversal" || !value) {
      return "펀딩비 + 미결제약정 급락 반등 전략";
    }
    return value;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        설정 정보를 불러오는 중...
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">설정</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          펀딩비/미결제약정 데모 트레이더 상태와 실행 진단
        </p>
      </div>

      {mode === "live" && (
        <div className="flex items-start gap-3 bg-red-900/20 border border-red-700 rounded-xl px-4 py-3">
          <svg
            className="w-5 h-5 text-red-500 shrink-0 mt-0.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div>
            <p className="text-sm font-semibold text-red-400">실거래 모드 활성화</p>
            <p className="text-xs text-red-400/80 mt-0.5">
              실제 자금이 위험에 노출됩니다. 주문 전 실행 중인 프로세스를 확인하세요.
            </p>
          </div>
        </div>
      )}

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="펀딩비/OI 데모 트레이더"
          sub="수집한 저시총 알트코인 스냅샷으로 동작하는 독립 데모 트레이더"
        />
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-3 min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  demoStatus?.running ? "bg-green-400 animate-pulse" : "bg-slate-600"
                }`}
              />
              <span className="text-sm font-semibold text-slate-200">
                {demoStatus?.running ? "실행 중" : demoStatus?.status ?? "알 수 없음"}
              </span>
              {demoStatus?.stale && (
                <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">
                  지연됨
                </span>
              )}
            </div>
            <div className="text-sm text-white">{strategyLabel(demoStatus?.strategy_name)}</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs text-slate-400">
              <div>
                <span className="text-slate-500">모드</span>{" "}
                <span className="font-semibold text-blue-300">{demoStatus?.mode?.toUpperCase() ?? "-"}</span>
              </div>
              <div>
                <span className="text-slate-500">감시 종목</span>{" "}
                <span className="text-slate-200">{demoStatus?.watched_instrument_count ?? 0}개</span>
              </div>
              <div>
                <span className="text-slate-500">증거금</span>{" "}
                <span className="text-slate-200">{renderUsd(demoMargin)}</span>
              </div>
              <div>
                <span className="text-slate-500">포지션 규모</span>{" "}
                <span className="text-slate-200">
                  {renderUsd(demoNotional)}{demoLeverage > 0 ? ` - ${demoLeverage}x` : ""}
                </span>
              </div>
              <div>
                <span className="text-slate-500">스냅샷</span>{" "}
                <span className="text-slate-200">{demoStatus?.snapshot_count_seen ?? 0}</span>
              </div>
              <div>
                <span className="text-slate-500">청산 오류</span>{" "}
                <span className={(demoStatus?.close_error_count ?? 0) > 0 ? "text-red-300" : "text-slate-200"}>
                  {demoStatus?.close_error_count ?? 0}
                </span>
              </div>
              <div>
                <span className="text-slate-500">마지막 실행</span>{" "}
                <span className="text-slate-200">{renderTime(demoStatus?.last_loop_at)}</span>
              </div>
              <div>
                <span className="text-slate-500">동기화 보정</span>{" "}
                <span className="text-slate-200">{demoStatus?.reconciliation_count ?? 0}</span>
              </div>
            </div>
          </div>
          <div className="w-64 shrink-0 rounded-lg border border-slate-800 bg-slate-950/30 p-3">
            <div className="text-xs font-semibold text-slate-300">현재 포지션</div>
            {demoOpenPosition ? (
              <div className="mt-2 space-y-1 text-xs text-slate-400">
                <div className="font-semibold text-white">{String(demoOpenPosition["inst_id"] ?? "-")}</div>
                <div>{String(demoOpenPosition["side"] ?? "long")} - 진입가 {String(demoOpenPosition["entry_price"] ?? "-")}</div>
                <div>수량 {String(demoOpenPosition["size"] ?? "-")}</div>
              </div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">열린 포지션 없음. 새 신호를 기다리는 중.</div>
            )}
          </div>
        </div>
      </div>

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="펀딩비/Basis 차익 모니터"
          sub="현물과 무기한 선물 가격 차이, 펀딩비, 스프레드 비용을 합쳐 시장중립 후보를 감시"
        />
        {!basisArbitrage || basisArbitrage.items.length === 0 ? (
          <p className="text-sm text-slate-500">아직 basis 차익 스냅샷이 없습니다.</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {basisArbitrage.items.slice(0, 3).map((row) => (
                <div key={row.inst_id} className={`rounded-lg border p-3 ${basisReadinessClass(row)}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{row.inst_id}</div>
                      <div className="mt-1 text-xs opacity-80">{basisSideLabel(row.candidate_side)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold">{Math.round(row.carry_score * 100)}</div>
                      <div className="text-[10px] uppercase tracking-wide opacity-70">점수</div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div><div className="opacity-60">Basis</div><div>{renderPct(row.basis_pct, 3)}</div></div>
                    <div><div className="opacity-60">8h 펀딩</div><div>{renderPct(row.funding_8h_pct, 4)}</div></div>
                    <div><div className="opacity-60">비용 후</div><div>{renderPct(row.net_funding_8h_after_cost_pct, 4)}</div></div>
                  </div>
                </div>
              ))}
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-800/70">
              <table className="w-full min-w-[980px] text-xs">
                <thead className="bg-slate-950/40 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">스왑</th>
                    <th className="px-3 py-2 text-left font-medium">현물</th>
                    <th className="px-3 py-2 text-left font-medium">점수</th>
                    <th className="px-3 py-2 text-right font-medium">Basis</th>
                    <th className="px-3 py-2 text-right font-medium">8h 펀딩</th>
                    <th className="px-3 py-2 text-right font-medium">일 펀딩</th>
                    <th className="px-3 py-2 text-right font-medium">왕복 비용</th>
                    <th className="px-3 py-2 text-right font-medium">비용 후</th>
                    <th className="px-3 py-2 text-left font-medium">포지션</th>
                    <th className="px-3 py-2 text-left font-medium">상태</th>
                    <th className="px-3 py-2 text-left font-medium">이유</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {basisArbitrage.items.map((row) => (
                    <tr key={row.inst_id} className={row.signal_ready ? "bg-emerald-500/5" : ""}>
                      <td className="px-3 py-2 font-semibold text-slate-200">{row.inst_id}</td>
                      <td className="px-3 py-2 text-slate-300">{row.spot_inst_id}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <ScoreBar value={row.carry_score} />
                          <span className="text-slate-300">{Math.round(row.carry_score * 100)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.basis_pct, 3)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.funding_8h_pct, 4)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.estimated_daily_funding_pct, 4)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.estimated_round_trip_cost_pct, 4)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.net_funding_8h_after_cost_pct, 4)}</td>
                      <td className="px-3 py-2 text-slate-300">{basisSideLabel(row.candidate_side)}</td>
                      <td className="px-3 py-2">
                        <span className={`rounded px-2 py-0.5 ${row.signal_ready ? "bg-emerald-500/20 text-emerald-200" : row.readiness === "watch" ? "bg-cyan-500/15 text-cyan-200" : "bg-slate-800 text-slate-400"}`}>
                          {basisReadinessLabel(row)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-500">{row.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="시장 괴리 모니터"
          sub="펀딩비, 미결제약정, 가격 급락, 스프레드, 체결 흐름, 호가창 불균형을 감시"
        />
        {!dislocation || dislocation.items.length === 0 ? (
          <p className="text-sm text-slate-500">최근 시장 스냅샷이 없습니다.</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {dislocation.items.slice(0, 3).map((row) => (
                <div key={row.inst_id} className={`rounded-lg border p-3 ${readinessClass(row)}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{row.inst_id}</div>
                      <div className="mt-1 text-xs opacity-80">{reasonLabel(row.reason)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold">{Math.round(row.dislocation_score * 100)}</div>
                      <div className="text-[10px] uppercase tracking-wide opacity-70">점수</div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <div className="opacity-60">가격 변동</div>
                      <div>{renderPct(row.lookback_return_pct)}</div>
                    </div>
                    <div>
                      <div className="opacity-60">펀딩비</div>
                      <div>{renderFunding(row.funding_rate)}</div>
                    </div>
                    <div>
                      <div className="opacity-60">OI</div>
                      <div>{renderPct(row.oi_change_pct)}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-800/70">
              <table className="w-full min-w-[920px] text-xs">
                <thead className="bg-slate-950/40 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">종목</th>
                    <th className="px-3 py-2 text-left font-medium">점수</th>
                    <th className="px-3 py-2 text-right font-medium">가격 변동</th>
                    <th className="px-3 py-2 text-right font-medium">펀딩비</th>
                    <th className="px-3 py-2 text-right font-medium">OI</th>
                    <th className="px-3 py-2 text-right font-medium">스프레드</th>
                    <th className="px-3 py-2 text-right font-medium">체결 흐름</th>
                    <th className="px-3 py-2 text-right font-medium">호가창</th>
                    <th className="px-3 py-2 text-left font-medium">상태</th>
                    <th className="px-3 py-2 text-left font-medium">이유</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {dislocation.items.map((row) => (
                    <tr key={row.inst_id} className={row.signal_ready ? "bg-red-500/5" : ""}>
                      <td className="px-3 py-2 font-semibold text-slate-200">{row.inst_id}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <ScoreBar value={row.dislocation_score} />
                          <span className="text-slate-300">{Math.round(row.dislocation_score * 100)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.lookback_return_pct)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderFunding(row.funding_rate)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.oi_change_pct)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{renderPct(row.spread_pct, 3)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{row.trade_imbalance.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{row.book_imbalance.toFixed(2)}</td>
                      <td className="px-3 py-2">
                        <span className={`rounded px-2 py-0.5 ${row.signal_ready ? "bg-red-500/20 text-red-200" : row.readiness === "watch" ? "bg-amber-500/15 text-amber-200" : "bg-slate-800 text-slate-400"}`}>
                          {readinessLabel(row)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-500">{reasonLabel(row.reason)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="실시간 로그"
          sub="신호, 주문, 실행 이벤트"
        />
        {logs.length === 0 ? (
          <p className="text-sm text-slate-500">아직 실행 로그가 없습니다.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-800/70">
            <div className="divide-y divide-slate-800/60">
              {logs.slice().reverse().map((log) => {
                const levelCls =
                  log.level === "error"
                    ? "text-red-400"
                    : log.level === "warning"
                      ? "text-amber-300"
                      : "text-slate-300";
                const ts = new Date(log.timestamp).toLocaleTimeString("ko-KR");
                return (
                  <div
                    key={log.id}
                    className="px-3 py-2 text-xs grid grid-cols-[88px_1fr] gap-2"
                  >
                    <div className="text-slate-500">{ts}</div>
                    <div className="space-y-0.5">
                      <div className={levelCls}>
                        <span className="font-semibold">{log.event}</span>
                        {(log.pair || log.strategy || log.timeframe) && (
                          <span className="text-slate-500">
                            {" "}
                            {[log.pair, log.strategy, log.timeframe].filter(Boolean).join(" / ")}
                          </span>
                        )}
                      </div>
                      <div className="text-slate-400 break-all">{renderLogText(log)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader title="실행 상태" sub="API, 데이터베이스, 거래소 연결 상태" />
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <span className="text-slate-400">데이터베이스</span>
            <span className={health?.db === "ok" ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
              {health?.db ?? "-"}
            </span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <span className="text-slate-400">OKX API</span>
            <span className={health?.okx_api.status === "ok" ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
              {health?.okx_api.status ?? "-"}
            </span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-slate-400">모드</span>
            <span className={mode === "live" ? "text-orange-400 font-semibold" : "text-blue-400 font-semibold"}>
              {mode?.toUpperCase() ?? "-"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
