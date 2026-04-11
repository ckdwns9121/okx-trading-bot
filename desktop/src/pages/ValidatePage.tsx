"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  runValidation,
  getValidationProgress,
  getValidationResults,
  deployToDemo,
  cancelValidation,
} from "@/lib/api";
import type {
  ValidationProgress,
  ValidationResult,
  StrategyRanking,
} from "@/lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

/* ── helpers ─────────────────────────────────────────────── */

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmt = (v: number) => v.toFixed(2);
const COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
];

type SortKey = keyof Pick<
  StrategyRanking,
  "composite_score" | "sharpe_ratio" | "max_drawdown" | "win_rate" | "total_pnl" | "trade_count"
>;

/* ── page ────────────────────────────────────────────────── */

export default function ValidatePage() {
  const [progress, setProgress] = useState<ValidationProgress | null>(null);
  const [results, setResults] = useState<ValidationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("composite_score");
  const [sortAsc, setSortAsc] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const flash = (m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(null), 4000);
  };

  // Load latest results on mount
  useEffect(() => {
    getValidationResults()
      .then((r) => { if (r) setResults(r); })
      .catch(() => {});
    getValidationProgress()
      .then((p) => {
        setProgress(p);
        if (p.phase !== "idle" && p.phase !== "complete" && p.phase !== "error" && p.phase !== "cancelled") {
          setRunning(true);
        }
      })
      .catch(() => {});
  }, []);

  // Polling
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const p = await getValidationProgress();
        setProgress(p);
        if (p.phase === "complete" || p.phase === "error" || p.phase === "cancelled") {
          setRunning(false);
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          if (p.phase === "complete") {
            const r = await getValidationResults();
            if (r) setResults(r);
            flash("검증 완료!");
          } else if (p.phase === "error") {
            flash(`오류: ${p.message}`);
          } else {
            flash("검증이 취소되었습니다.");
          }
        }
      } catch {
        /* ignore transient errors */
      }
    }, 2000);
  }, []);

  useEffect(() => {
    if (running) startPolling();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [running, startPolling]);

  async function handleRun() {
    try {
      await runValidation();
      setRunning(true);
      flash("검증 파이프라인 시작됨");
    } catch (e) {
      flash(`시작 실패: ${(e as Error).message}`);
    }
  }

  async function handleCancel() {
    try {
      await cancelValidation();
      flash("취소 요청됨");
    } catch (e) {
      flash(`취소 실패: ${(e as Error).message}`);
    }
  }

  async function handleDeploy(name: string) {
    try {
      const res = await deployToDemo(name);
      flash(res.message);
    } catch (e) {
      flash(`배포 실패: ${(e as Error).message}`);
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  const sortedRankings = results
    ? [...results.rankings].sort((a, b) => {
        const diff = (a[sortKey] as number) - (b[sortKey] as number);
        return sortAsc ? diff : -diff;
      })
    : [];

  const isActive = running && progress && !["idle", "complete", "error", "cancelled"].includes(progress.phase);

  // Chart data: top 10
  const chartData = sortedRankings.slice(0, 10).map((r) => ({
    name: `${r.strategy_name.replace("example_", "")}`,
    score: r.composite_score,
    sharpe: r.sharpe_ratio,
    winRate: r.win_rate,
    mdd: r.max_drawdown,
  }));

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">전략 검증</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          모든 전략을 자동으로 백테스트하고 순위를 매긴 뒤, 상위 전략을 최적화합니다
        </p>
      </div>

      {/* Flash message */}
      {msg && (
        <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg px-4 py-2.5 text-sm text-blue-300">
          {msg}
        </div>
      )}

      {/* ── Controls ───────────────────────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">파이프라인 실행</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              10개 전략 × BTC/ETH × 1H/4H = 40회 백테스트 + 상위 3개 최적화
            </p>
          </div>
          <div className="flex gap-2">
            {!isActive ? (
              <button
                onClick={handleRun}
                className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                전체 검증 실행
              </button>
            ) : (
              <button
                onClick={handleCancel}
                className="px-5 py-2 bg-red-700 hover:bg-red-600 text-white text-sm font-medium rounded-lg transition-colors"
              >
                취소
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        {isActive && progress && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{progress.message}</span>
              <span>{progress.pct}%</span>
            </div>
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${progress.pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Last run info */}
        {results && !isActive && (
          <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
            <span>마지막 실행: {new Date(results.completed_at).toLocaleString("ko-KR")}</span>
            <span>{results.total_backtests}회 백테스트</span>
            <span>{results.duration_seconds}초 소요</span>
          </div>
        )}
      </div>

      {/* ── Charts ─────────────────────────────────────────── */}
      {results && chartData.length > 0 && (
        <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">상위 전략 비교</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <Bar dataKey="score" name="Composite Score" radius={[4, 4, 0, 0]}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Optimized strategies ──────────────────────────── */}
      {results && results.optimized.length > 0 && (
        <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">최적화 결과 (상위 전략)</h2>
          <div className="space-y-3">
            {results.optimized.map((o) => (
              <div
                key={o.strategy_name}
                className="flex items-center justify-between border border-slate-800 rounded-lg p-4"
              >
                <div>
                  <p className="text-sm font-semibold text-white">{o.strategy_name}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    최적화 파라미터: {Object.entries(o.optimized_params).map(([k, v]) => `${k}=${v}`).join(", ")}
                  </p>
                  <p className="text-xs text-slate-500">
                    점수: {o.before_score} → {o.after_score}
                  </p>
                </div>
                <button
                  onClick={() => handleDeploy(o.strategy_name)}
                  className="px-4 py-2 bg-green-700 hover:bg-green-600 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
                >
                  데모 배포
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Rankings table ────────────────────────────────── */}
      {results && sortedRankings.length > 0 && (
        <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">
            전체 순위 ({sortedRankings.length}개 결과)
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
                  <th className="pb-3 pr-3 font-medium">#</th>
                  <th className="pb-3 pr-3 font-medium">전략</th>
                  <th className="pb-3 pr-3 font-medium">페어</th>
                  <th className="pb-3 pr-3 font-medium">TF</th>
                  {(
                    [
                      ["composite_score", "점수"],
                      ["sharpe_ratio", "Sharpe"],
                      ["max_drawdown", "MDD"],
                      ["win_rate", "승률"],
                      ["total_pnl", "PnL"],
                      ["trade_count", "거래수"],
                    ] as [SortKey, string][]
                  ).map(([key, label]) => (
                    <th
                      key={key}
                      onClick={() => toggleSort(key)}
                      className="pb-3 pr-3 font-medium cursor-pointer hover:text-white select-none"
                    >
                      {label} {sortKey === key ? (sortAsc ? "▲" : "▼") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {sortedRankings.map((r, i) => (
                  <tr key={`${r.strategy_name}-${r.pair}-${r.timeframe}`} className="hover:bg-slate-800/20">
                    <td className="py-2.5 pr-3 text-slate-500">{i + 1}</td>
                    <td className="py-2.5 pr-3 font-medium text-white text-xs">{r.strategy_name}</td>
                    <td className="py-2.5 pr-3 text-slate-400">{r.pair.replace("-USDT-SWAP", "")}</td>
                    <td className="py-2.5 pr-3 text-slate-400">{r.timeframe}</td>
                    <td className="py-2.5 pr-3 font-semibold text-blue-400">{fmt(r.composite_score)}</td>
                    <td className="py-2.5 pr-3 text-slate-300">{fmt(r.sharpe_ratio)}</td>
                    <td className="py-2.5 pr-3 text-slate-300">{pct(r.max_drawdown)}</td>
                    <td className="py-2.5 pr-3 text-slate-300">{pct(r.win_rate)}</td>
                    <td className={`py-2.5 pr-3 font-medium ${r.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${fmt(r.total_pnl)}
                    </td>
                    <td className="py-2.5 pr-3 text-slate-400">{r.trade_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!results && !isActive && (
        <div className="flex flex-col items-center justify-center h-48 text-slate-500 text-sm">
          <p>아직 검증 결과가 없습니다.</p>
          <p className="text-xs mt-1">위의 &quot;전체 검증 실행&quot; 버튼을 눌러 시작하세요.</p>
        </div>
      )}
    </div>
  );
}
