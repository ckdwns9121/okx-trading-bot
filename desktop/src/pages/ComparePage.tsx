"use client";

import { useState, useEffect, useMemo } from "react";
import { getStrategyInfos, runComparison } from "@/lib/api";
import type { CompareResult, StrategyInfo } from "@/lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";

// ---------------------------------------------------------------------------
// Shared metric card
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-[#161b27] border border-slate-800 rounded-xl p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color ?? "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-600 mt-0.5">{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heatmap color helper
// ---------------------------------------------------------------------------

function pnlColor(value: number, min: number, max: number): string {
  if (min === max) return "bg-slate-800";
  const range = max - min;
  const normalized = (value - min) / range; // 0 = worst, 1 = best
  if (normalized >= 0.75) return "bg-emerald-900/80 text-emerald-300";
  if (normalized >= 0.5) return "bg-emerald-900/40 text-emerald-400";
  if (normalized >= 0.25) return "bg-red-900/30 text-red-400";
  return "bg-red-900/60 text-red-300";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIMEFRAMES = [
  "1m", "3m", "5m", "15m", "30m",
  "1H", "2H", "4H", "6H", "12H",
  "1D", "1W",
];

const PAIR_COLORS = [
  "#60a5fa", "#f472b6", "#34d399", "#fbbf24", "#a78bfa",
  "#fb923c", "#22d3ee", "#e879f9", "#4ade80", "#f87171",
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ComparePage() {
  // Strategy list
  const [strategyInfos, setStrategyInfos] = useState<StrategyInfo[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<Set<string>>(new Set());

  // Pairs
  const [pairs, setPairs] = useState<string[]>(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]);
  const [pairInput, setPairInput] = useState("");

  // Config
  const [timeframe, setTimeframe] = useState("4H");
  const [startDate, setStartDate] = useState("2025-06-01");
  const [endDate, setEndDate] = useState("2026-03-25");
  const [initialBalance, setInitialBalance] = useState(10000);
  const [leverage, setLeverage] = useState(1);

  // Results
  const [results, setResults] = useState<CompareResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail popup
  const [selectedCell, setSelectedCell] = useState<CompareResult | null>(null);

  // Load strategies on mount
  useEffect(() => {
    getStrategyInfos()
      .then((infos) => {
        setStrategyInfos(infos);
        setSelectedStrategies(new Set(infos.map((i) => i.name)));
      })
      .catch(() => {});
  }, []);

  // Derived data
  const uniqueStrategies = useMemo(
    () => [...new Set(results.map((r) => r.strategy))],
    [results],
  );
  const uniquePairs = useMemo(
    () => [...new Set(results.map((r) => r.pair))],
    [results],
  );

  const allPnls = useMemo(() => results.map((r) => r.total_pnl), [results]);
  const minPnl = useMemo(() => Math.min(...allPnls, 0), [allPnls]);
  const maxPnl = useMemo(() => Math.max(...allPnls, 0), [allPnls]);

  // Rankings
  const rankings = useMemo(() => {
    if (results.length === 0) return null;

    // Average Sharpe per strategy
    const stratSharpes: Record<string, number[]> = {};
    const stratReturns: Record<string, number[]> = {};
    for (const r of results) {
      (stratSharpes[r.strategy] ??= []).push(r.sharpe_ratio);
      (stratReturns[r.strategy] ??= []).push(r.total_pnl);
    }

    const avgSharpe = Object.entries(stratSharpes).map(([s, vals]) => ({
      strategy: s,
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    }));
    const bestOverall = avgSharpe.sort((a, b) => b.avg - a.avg)[0];

    // Most consistent: lowest std dev of returns
    const consistency = Object.entries(stratReturns).map(([s, vals]) => {
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const variance = vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length;
      return { strategy: s, stdDev: Math.sqrt(variance) };
    });
    const mostConsistent = consistency.sort((a, b) => a.stdDev - b.stdDev)[0];

    // Best per pair
    const bestPerPair: Record<string, { strategy: string; pnl: number }> = {};
    for (const r of results) {
      if (!bestPerPair[r.pair] || r.total_pnl > bestPerPair[r.pair].pnl) {
        bestPerPair[r.pair] = { strategy: r.strategy, pnl: r.total_pnl };
      }
    }

    return { bestOverall, mostConsistent, bestPerPair };
  }, [results]);

  // Chart data
  const pnlChartData = useMemo(() => {
    return uniqueStrategies.map((s) => {
      const row: Record<string, string | number> = { strategy: s };
      for (const p of uniquePairs) {
        const r = results.find((x) => x.strategy === s && x.pair === p);
        row[p] = r ? r.total_pnl : 0;
      }
      return row;
    });
  }, [results, uniqueStrategies, uniquePairs]);

  const sharpeChartData = useMemo(() => {
    return uniqueStrategies.map((s) => {
      const row: Record<string, string | number> = { strategy: s };
      for (const p of uniquePairs) {
        const r = results.find((x) => x.strategy === s && x.pair === p);
        row[p] = r ? r.sharpe_ratio : 0;
      }
      return row;
    });
  }, [results, uniqueStrategies, uniquePairs]);

  // Helpers
  function getResult(strategy: string, pair: string): CompareResult | undefined {
    return results.find((r) => r.strategy === strategy && r.pair === pair);
  }

  function avgForStrategy(strategy: string): number {
    const strats = results.filter((r) => r.strategy === strategy);
    if (strats.length === 0) return 0;
    return strats.reduce((a, b) => a + b.total_pnl, 0) / strats.length;
  }

  function avgForPair(pair: string): number {
    const ps = results.filter((r) => r.pair === pair);
    if (ps.length === 0) return 0;
    return ps.reduce((a, b) => a + b.total_pnl, 0) / ps.length;
  }

  // Toggle strategy selection
  function toggleStrategy(name: string) {
    setSelectedStrategies((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleAll() {
    if (selectedStrategies.size === strategyInfos.length) {
      setSelectedStrategies(new Set());
    } else {
      setSelectedStrategies(new Set(strategyInfos.map((i) => i.name)));
    }
  }

  function addPair() {
    const p = pairInput.trim().toUpperCase();
    if (p && !pairs.includes(p)) {
      setPairs([...pairs, p]);
    }
    setPairInput("");
  }

  function removePair(p: string) {
    setPairs(pairs.filter((x) => x !== p));
  }

  // Run comparison
  async function handleRun() {
    const strats = [...selectedStrategies];
    if (strats.length === 0 || pairs.length === 0) return;

    setLoading(true);
    setError(null);
    setResults([]);
    setSelectedCell(null);

    try {
      const data = await runComparison({
        strategies: strats,
        pairs,
        timeframe,
        start_date: startDate,
        end_date: endDate,
        initial_balance: initialBalance,
        leverage,
      });
      setResults(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "비교 실패");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-6">
      <h1 className="text-2xl font-bold">전략 비교</h1>
      <p className="text-sm text-slate-400">
        여러 전략을 여러 거래쌍에 걸쳐 나란히 비교합니다.
      </p>

      {/* ── Configuration Panel ──────────────────────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 space-y-5">
        <h2 className="text-lg font-semibold">설정</h2>

        {/* Strategy selection */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm text-slate-400">전략</label>
            <button
              onClick={toggleAll}
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              {selectedStrategies.size === strategyInfos.length ? "전체 해제" : "전체 선택"}
            </button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
            {strategyInfos.map((info) => (
              <label
                key={info.name}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer transition-colors
                  ${selectedStrategies.has(info.name)
                    ? "border-blue-500 bg-blue-500/10 text-blue-300"
                    : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600"}`}
                title={info.description}
              >
                <input
                  type="checkbox"
                  checked={selectedStrategies.has(info.name)}
                  onChange={() => toggleStrategy(info.name)}
                  className="sr-only"
                />
                <span className={`w-3 h-3 rounded-sm border flex-shrink-0 flex items-center justify-center
                  ${selectedStrategies.has(info.name) ? "bg-blue-500 border-blue-500" : "border-slate-600"}`}>
                  {selectedStrategies.has(info.name) && (
                    <svg className="w-2 h-2 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={3}>
                      <path d="M2 6l3 3 5-5" />
                    </svg>
                  )}
                </span>
                <span className="truncate">{info.name}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Pairs */}
        <div>
          <label className="text-sm text-slate-400 mb-2 block">거래쌍</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {pairs.map((p) => (
              <span
                key={p}
                className="flex items-center gap-1 px-3 py-1 bg-slate-800 border border-slate-700 rounded-lg text-sm"
              >
                {p}
                <button
                  onClick={() => removePair(p)}
                  className="text-slate-500 hover:text-red-400 ml-1"
                >
                  x
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={pairInput}
              onChange={(e) => setPairInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addPair()}
              placeholder="거래쌍 추가, 예: DOGE-USDT-SWAP"
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={addPair}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm"
            >
              추가
            </button>
          </div>
        </div>

        {/* Parameters row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">타임프레임</label>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">시작일</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">종료일</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">초기 자본 ($)</label>
            <input
              type="number"
              value={initialBalance}
              onChange={(e) => setInitialBalance(Number(e.target.value))}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">레버리지</label>
            <input
              type="number"
              min={1}
              max={125}
              value={leverage}
              onChange={(e) => setLeverage(Number(e.target.value))}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        {/* Run button */}
        <button
          onClick={handleRun}
          disabled={loading || selectedStrategies.size === 0 || pairs.length === 0}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500
                     rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
        >
          {loading && (
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          {loading
            ? `${selectedStrategies.size}개 전략 x ${pairs.length}개 거래쌍 실행 중...`
            : "비교 실행"}
        </button>

        {error && (
          <p className="text-sm text-red-400 mt-2">{error}</p>
        )}
      </div>

      {/* ── Loading skeleton ─────────────────────────────────────────── */}
      {loading && (
        <div className="space-y-4">
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 animate-pulse">
            <div className="h-6 bg-slate-800 rounded w-48 mb-4" />
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-10 bg-slate-800 rounded" />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────── */}
      {results.length > 0 && !loading && (
        <>
          {/* Rankings */}
          {rankings && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <MetricCard
                label="종합 최고 (평균 Sharpe)"
                value={rankings.bestOverall.strategy}
                sub={`평균 Sharpe: ${rankings.bestOverall.avg.toFixed(3)}`}
                color="text-emerald-400"
              />
              <MetricCard
                label="가장 안정적 (최저 표준편차)"
                value={rankings.mostConsistent.strategy}
                sub={`표준편차: $${rankings.mostConsistent.stdDev.toFixed(2)}`}
                color="text-blue-400"
              />
              <div className="bg-[#161b27] border border-slate-800 rounded-xl p-4">
                <p className="text-xs text-slate-500 mb-2">거래쌍별 최고</p>
                <div className="space-y-1">
                  {Object.entries(rankings.bestPerPair).map(([pair, { strategy, pnl }]) => (
                    <div key={pair} className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">{pair}</span>
                      <span className="text-emerald-400 font-medium">
                        {strategy}{" "}
                        <span className="text-slate-500">(${pnl.toFixed(0)})</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Heatmap Table */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 overflow-x-auto">
            <h2 className="text-lg font-semibold mb-4">손익 히트맵</h2>
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left py-2 px-3 text-slate-500 font-medium">전략</th>
                  {uniquePairs.map((p) => (
                    <th key={p} className="text-right py-2 px-3 text-slate-500 font-medium">{p}</th>
                  ))}
                  <th className="text-right py-2 px-3 text-slate-500 font-medium">평균</th>
                </tr>
              </thead>
              <tbody>
                {uniqueStrategies.map((s) => (
                  <tr key={s} className="border-t border-slate-800">
                    <td className="py-2 px-3 text-slate-300 font-medium">{s}</td>
                    {uniquePairs.map((p) => {
                      const r = getResult(s, p);
                      const pnl = r?.total_pnl ?? 0;
                      return (
                        <td
                          key={p}
                          className={`py-2 px-3 text-right rounded cursor-pointer transition-colors hover:ring-1 hover:ring-blue-500 ${pnlColor(pnl, minPnl, maxPnl)}`}
                          onClick={() => r && setSelectedCell(r)}
                        >
                          ${pnl.toFixed(0)}
                        </td>
                      );
                    })}
                    <td className="py-2 px-3 text-right text-slate-400">
                      ${avgForStrategy(s).toFixed(0)}
                    </td>
                  </tr>
                ))}
                {/* Pair averages row */}
                <tr className="border-t border-slate-700">
                  <td className="py-2 px-3 text-slate-500 font-medium">평균</td>
                  {uniquePairs.map((p) => (
                    <td key={p} className="py-2 px-3 text-right text-slate-400">
                      ${avgForPair(p).toFixed(0)}
                    </td>
                  ))}
                  <td className="py-2 px-3 text-right text-slate-500">-</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Detail popup */}
          {selectedCell && (
            <div className="bg-[#161b27] border border-blue-500/30 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">
                  {selectedCell.strategy} · {selectedCell.pair}
                </h3>
                <button
                  onClick={() => setSelectedCell(null)}
                  className="text-slate-500 hover:text-white text-sm"
                >
                  닫기
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                <MetricCard
                  label="총 손익"
                  value={`$${selectedCell.total_pnl.toFixed(2)}`}
                  color={selectedCell.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
                />
                <MetricCard
                  label="승률"
                  value={`${(selectedCell.win_rate * 100).toFixed(1)}%`}
                />
                <MetricCard
                  label="최대 낙폭"
                  value={`${(selectedCell.max_drawdown * 100).toFixed(1)}%`}
                  color="text-red-400"
                />
                <MetricCard
                  label="Sharpe 비율"
                  value={selectedCell.sharpe_ratio.toFixed(3)}
                />
                <MetricCard
                  label="거래 수"
                  value={String(selectedCell.trade_count)}
                />
                <MetricCard
                  label="수익 팩터"
                  value={selectedCell.profit_factor.toFixed(2)}
                />
              </div>
            </div>
          )}

          {/* PnL Bar Chart */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6">
            <h2 className="text-lg font-semibold mb-4">전략별 손익</h2>
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={pnlChartData} margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="strategy"
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                  angle={-30}
                  textAnchor="end"
                  height={60}
                />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                  labelStyle={{ color: "#f1f5f9" }}
                />
                <Legend />
                {uniquePairs.map((p, i) => (
                  <Bar
                    key={p}
                    dataKey={p}
                    fill={PAIR_COLORS[i % PAIR_COLORS.length]}
                    radius={[4, 4, 0, 0]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Sharpe Ratio Bar Chart */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6">
            <h2 className="text-lg font-semibold mb-4">전략별 Sharpe 비율</h2>
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={sharpeChartData} margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="strategy"
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                  angle={-30}
                  textAnchor="end"
                  height={60}
                />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                  labelStyle={{ color: "#f1f5f9" }}
                />
                <Legend />
                {uniquePairs.map((p, i) => (
                  <Bar
                    key={p}
                    dataKey={p}
                    fill={PAIR_COLORS[i % PAIR_COLORS.length]}
                    radius={[4, 4, 0, 0]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
