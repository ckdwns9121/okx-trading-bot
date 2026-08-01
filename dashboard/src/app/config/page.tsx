"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getHealth,
  getRiskStatus,
  getTradingLogs,
  resetKillSwitch,
  tripKillSwitch,
} from "@/lib/api";
import type { HealthStatus, RiskStatus, TradingLogEvent } from "@/lib/types";

const LIMIT_LABELS: Record<string, string> = {
  max_order_notional_usd: "주문당 최대 금액 (USD)",
  max_instrument_notional_usd: "종목당 최대 포지션 (USD)",
  max_total_exposure_usd: "총 노출 한도 (USD)",
  max_price_deviation_pct: "가격 괴리 한도 (%)",
  max_daily_loss_usd: "일일 손실 한도 (USD)",
  max_orders_per_minute: "분당 최대 주문 수",
};

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function ConfigPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [logs, setLogs] = useState<TradingLogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [riskBusy, setRiskBusy] = useState(false);

  const load = useCallback(async () => {
    const [h, r, lg] = await Promise.allSettled([
      getHealth(),
      getRiskStatus(),
      getTradingLogs(120),
    ]);
    if (h.status === "fulfilled") setHealth(h.value);
    if (r.status === "fulfilled") setRisk(r.value);
    if (lg.status === "fulfilled") setLogs(lg.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const [nextRisk, nextLogs] = await Promise.all([
          getRiskStatus(),
          getTradingLogs(120),
        ]);
        setRisk(nextRisk);
        setLogs(nextLogs);
      } catch {
        // Keep the current dashboard state on transient API errors.
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  async function onEmergencyStop() {
    const reason = window.prompt("긴급 정지 사유를 입력하세요:", "수동 긴급 정지");
    if (!reason) return;
    setRiskBusy(true);
    try {
      await tripKillSwitch(reason);
      setRisk(await getRiskStatus());
    } catch (error) {
      window.alert(`킬스위치 발동 실패: ${String(error)}`);
    } finally {
      setRiskBusy(false);
    }
  }

  async function onResumeTrading() {
    if (!window.confirm("킬스위치를 해제하고 거래를 다시 허용할까요?")) return;
    setRiskBusy(true);
    try {
      await resetKillSwitch();
      setRisk(await getRiskStatus());
    } catch (error) {
      window.alert(`킬스위치 해제 실패: ${String(error)}`);
    } finally {
      setRiskBusy(false);
    }
  }

  const mode = health?.okx_api.mode ?? null;

  function renderLogText(log: TradingLogEvent): string {
    if (typeof log.message === "string" && log.message.trim().length > 0) {
      return log.message;
    }
    if (log.details && Object.keys(log.details).length > 0) {
      return JSON.stringify(log.details);
    }
    return "-";
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
        <p className="text-sm text-slate-500 mt-0.5">실행 진단과 런타임 로그</p>
      </div>

      {mode === "live" && (
        <div className="flex items-start gap-3 bg-red-900/20 border border-red-700 rounded-xl px-4 py-3">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
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
        <SectionHeader title="리스크 안전장치" sub="모든 주문이 통과해야 하는 pre-trade 한도와 킬스위치" />
        {!risk ? (
          <p className="text-sm text-slate-500">리스크 상태를 불러오지 못했습니다.</p>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    risk.kill_switch.tripped ? "bg-red-500 animate-pulse" : "bg-green-400"
                  }`}
                />
                <span className="text-sm font-semibold text-slate-200">
                  {risk.kill_switch.tripped ? "킬스위치 발동됨 — 신규 진입 차단" : "정상 — 거래 허용"}
                </span>
              </div>
              {risk.kill_switch.tripped ? (
                <button
                  onClick={onResumeTrading}
                  disabled={riskBusy}
                  className="rounded-lg border border-emerald-600 bg-emerald-600/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/20 disabled:opacity-50"
                >
                  거래 재개
                </button>
              ) : (
                <button
                  onClick={onEmergencyStop}
                  disabled={riskBusy}
                  className="rounded-lg border border-red-600 bg-red-600/10 px-3 py-1.5 text-xs font-semibold text-red-300 hover:bg-red-600/20 disabled:opacity-50"
                >
                  긴급 정지
                </button>
              )}
            </div>
            {risk.kill_switch.tripped && (
              <div className="rounded-lg border border-red-700/50 bg-red-900/15 px-3 py-2 text-xs text-red-300">
                사유: {risk.kill_switch.reason ?? "-"}
                {risk.kill_switch.changed_at && (
                  <span className="text-red-400/70">
                    {" "}
                    ({new Date(risk.kill_switch.changed_at).toLocaleString("ko-KR")},{" "}
                    {risk.kill_switch.source ?? "unknown"})
                  </span>
                )}
              </div>
            )}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              {Object.entries(risk.limits).map(([key, value]) => (
                <div key={key} className="rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2">
                  <div className="text-slate-500">{LIMIT_LABELS[key] ?? key}</div>
                  <div className="mt-0.5 font-semibold text-slate-200">
                    {Number(value).toLocaleString("en-US")}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader title="실시간 로그" sub="신호, 주문, 실행 이벤트" />
        {logs.length === 0 ? (
          <p className="text-sm text-slate-500">아직 실행 로그가 없습니다.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-800/70">
            <div className="divide-y divide-slate-800/60">
              {logs.slice().reverse().map((log) => {
                const levelCls = log.level === "error" ? "text-red-400" : log.level === "warning" ? "text-amber-300" : "text-slate-300";
                const ts = new Date(log.timestamp).toLocaleTimeString("ko-KR");
                return (
                  <div key={log.id} className="px-3 py-2 text-xs grid grid-cols-[88px_1fr] gap-2">
                    <div className="text-slate-500">{ts}</div>
                    <div className="space-y-0.5">
                      <div className={levelCls}>
                        <span className="font-semibold">{log.event}</span>
                        {(log.pair || log.strategy || log.timeframe) && (
                          <span className="text-slate-500"> {[log.pair, log.strategy, log.timeframe].filter(Boolean).join(" / ")}</span>
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
            <span className={health?.db === "ok" ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>{health?.db ?? "-"}</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <span className="text-slate-400">OKX API</span>
            <span className={health?.okx_api.status === "ok" ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>{health?.okx_api.status ?? "-"}</span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-slate-400">모드</span>
            <span className={mode === "live" ? "text-orange-400 font-semibold" : "text-blue-400 font-semibold"}>{mode?.toUpperCase() ?? "-"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
