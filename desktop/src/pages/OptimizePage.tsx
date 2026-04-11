"use client";

import { useState, useEffect, useMemo } from "react";
import { getStrategies, runOptimization, getParamSpace } from "@/lib/api";
import type { OptimizationResult, TrialResult, ParamSpace } from "@/lib/types";
import {
  LineChart,
  Line,
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
// Shared metric card (matches backtest page)
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
// Convergence chart data builder
// ---------------------------------------------------------------------------

function buildConvergence(trials: TrialResult[]) {
  let best = -Infinity;
  return trials.map((t) => {
    if (t.score > best) best = t.score;
    return {
      trial: t.trial_number,
      score: parseFloat(t.score.toFixed(4)),
      bestSoFar: parseFloat(best.toFixed(4)),
    };
  });
}

// ---------------------------------------------------------------------------
// TIMEFRAMES
// ---------------------------------------------------------------------------

const TIMEFRAMES = [
  "1m", "3m", "5m", "15m", "30m",
  "1H", "2H", "4H", "6H", "12H",
  "1D", "1W",
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OptimizePage() {
  // Form state
  const [strategies, setStrategies] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("");
  const [pair, setPair] = useState("BTC-USDT-SWAP");
  const [timeframe, setTimeframe] = useState("1H");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-06-01");
  const [iterations, setIterations] = useState(50);
  const [split, setSplit] = useState(70);
  const [objective, setObjective] = useState("sharpe_ratio");
  const [balance, setBalance] = useState(10000);
  const [leverage, setLeverage] = useState(1);

  // Result state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [paramSpace, setParamSpace] = useState<ParamSpace | null>(null);

  // Load strategies on mount
  useEffect(() => {
    getStrategies()
      .then((s) => {
        setStrategies(s);
        if (s.length > 0) setStrategy(s[0]);
      })
      .catch(() => setStrategies([]));
  }, []);

  // Load param space when strategy changes
  useEffect(() => {
    if (!strategy) return;
    getParamSpace(strategy)
      .then(setParamSpace)
      .catch(() => setParamSpace(null));
  }, [strategy]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runOptimization({
        strategy_name: strategy,
        pair,
        timeframe,
        start_date: startDate,
        end_date: endDate,
        initial_balance: balance,
        leverage,
        n_iterations: iterations,
        walk_forward_split: split / 100,
        objective,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "최적화 실패");
    } finally {
      setLoading(false);
    }
  }

  // Sorted top 10 trials
  const top10 = useMemo(() => {
    if (!result) return [];
    return [...result.trials]
      .sort((a, b) => b.score - a.score)
      .slice(0, 10);
  }, [result]);

  // Overfitting check
  const overfitting = useMemo(() => {
    if (!result || result.trials.length === 0) return false;
    const best = [...result.trials].sort((a, b) => b.score - a.score)[0];
    if (best.val_sharpe <= 0) return best.train_sharpe > 0;
    return best.train_sharpe / best.val_sharpe > 2;
  }, [result]);

  // Convergence data
  const convergenceData = useMemo(() => {
    if (!result) return [];
    return buildConvergence(result.trials);
  }, [result]);

  // Train vs Val comparison for best trial
  const comparisonData = useMemo(() => {
    if (!result || result.trials.length === 0) return [];
    const best = [...result.trials].sort((a, b) => b.score - a.score)[0];
    return [
      { name: "Sharpe", "학습": parseFloat(best.train_sharpe.toFixed(2)), "검증": parseFloat(best.val_sharpe.toFixed(2)) },
      { name: "승률 %", "학습": parseFloat((best.train_win_rate * 100).toFixed(1)), "검증": parseFloat((best.val_win_rate * 100).toFixed(1)) },
    ];
  }, [result]);

  const inputCls =
    "w-full bg-[#0f1117] border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500";
  const labelCls = "text-xs text-slate-400 mb-1 block";

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">파라미터 최적화</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          워크포워드 검증을 활용한 베이지안 최적화로 최적 전략 파라미터를 탐색합니다
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-900/20 border border-blue-800/50 rounded-xl px-4 py-3">
        <svg
          className="w-4 h-4 text-blue-400 shrink-0 mt-0.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        <p className="text-xs text-blue-300/90">
          최적화는 과적합 방지를 위해 워크포워드 검증을 사용합니다. 데이터는
          학습 기간과 검증 기간으로 분리되며 &mdash; 검증 성과만이 최적 파라미터를 결정합니다.
        </p>
      </div>

      {/* Form */}
      <form
        onSubmit={handleSubmit}
        className="bg-[#161b27] border border-slate-800 rounded-xl p-6"
      >
        <h2 className="text-sm font-semibold text-white mb-4">설정</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* 전략 */}
          <div>
            <label className={labelCls}>전략</label>
            <select
              className={inputCls}
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              required
            >
              {strategies.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {/* 거래쌍 */}
          <div>
            <label className={labelCls}>거래쌍</label>
            <input
              className={inputCls}
              value={pair}
              onChange={(e) => setPair(e.target.value)}
              required
            />
          </div>

          {/* 타임프레임 */}
          <div>
            <label className={labelCls}>타임프레임</label>
            <select
              className={inputCls}
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </div>

          {/* 시작일 */}
          <div>
            <label className={labelCls}>시작일</label>
            <input
              type="date"
              className={inputCls}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              required
            />
          </div>

          {/* 종료일 */}
          <div>
            <label className={labelCls}>종료일</label>
            <input
              type="date"
              className={inputCls}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              required
            />
          </div>

          {/* 목표 */}
          <div>
            <label className={labelCls}>목표 지표</label>
            <select
              className={inputCls}
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
            >
              <option value="sharpe_ratio">Sharpe 비율</option>
              <option value="total_pnl">총 손익</option>
              <option value="win_rate">승률</option>
            </select>
          </div>

          {/* 초기 자본 */}
          <div>
            <label className={labelCls}>초기 자본 ($)</label>
            <input
              type="number"
              className={inputCls}
              value={balance}
              onChange={(e) => setBalance(Number(e.target.value))}
              min={100}
              required
            />
          </div>

          {/* 레버리지 */}
          <div>
            <label className={labelCls}>레버리지</label>
            <input
              type="number"
              className={inputCls}
              value={leverage}
              onChange={(e) => setLeverage(Number(e.target.value))}
              min={1}
              max={125}
              required
            />
          </div>

          {/* 반복 횟수 */}
          <div>
            <label className={labelCls}>
              반복 횟수: {iterations}
            </label>
            <input
              type="range"
              className="w-full accent-blue-500"
              value={iterations}
              onChange={(e) => setIterations(Number(e.target.value))}
              min={20}
              max={100}
              step={5}
            />
            <div className="flex justify-between text-[10px] text-slate-600 mt-0.5">
              <span>20</span>
              <span>100</span>
            </div>
          </div>

          {/* 워크포워드 분할 */}
          <div className="md:col-span-2">
            <label className={labelCls}>
              워크포워드 분할: {split}% 학습 / {100 - split}% 검증
            </label>
            <input
              type="range"
              className="w-full accent-blue-500"
              value={split}
              onChange={(e) => setSplit(Number(e.target.value))}
              min={50}
              max={90}
              step={5}
            />
            <div className="flex justify-between text-[10px] text-slate-600 mt-0.5">
              <span>50%</span>
              <span>90%</span>
            </div>
          </div>
        </div>

        {/* Param space preview */}
        {paramSpace && Object.keys(paramSpace).length > 0 && (
          <div className="mt-4 p-3 bg-[#0f1117] rounded-lg border border-slate-700/50">
            <p className="text-xs text-slate-500 mb-2">파라미터 탐색 범위</p>
            <div className="flex flex-wrap gap-3">
              {Object.entries(paramSpace).map(([name, [lo, hi]]) => (
                <span
                  key={name}
                  className="text-xs bg-slate-800 text-slate-300 px-2 py-1 rounded"
                >
                  {name}: [{lo}, {hi}]
                </span>
              ))}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !strategy}
          className="mt-5 w-full md:w-auto px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500
                     text-white transition-colors duration-150"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  fill="none"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              최적화 중...
            </span>
          ) : (
            "최적화 실행"
          )}
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-xl px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            결과 &mdash; {result.strategy_name} &middot; {result.pair}
          </h2>

          {/* Overfitting warning */}
          {overfitting && (
            <div className="flex items-start gap-3 bg-yellow-900/20 border border-yellow-800/50 rounded-xl px-4 py-3">
              <svg
                className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <p className="text-xs text-yellow-400/90">
                <strong>과적합 가능성이 감지되었습니다.</strong> 학습 Sharpe가 검증 Sharpe의 2배를 초과합니다.
                파라미터 수를 줄이거나, 데이터 범위를 늘리거나, 검증 구간을 넓히는 것을 고려하세요.
              </p>
            </div>
          )}

          {/* Metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="최고 점수"
              value={result.best_score.toFixed(4)}
              sub={objective}
              color={result.best_score > 0 ? "text-green-400" : "text-red-400"}
            />
            <MetricCard
              label="총 시도 횟수"
              value={String(result.total_trials)}
              sub={`${iterations}회 요청 중`}
            />
            <MetricCard
              label="학습 기간"
              value={result.train_period.split(" to ")[0]?.slice(0, 10) ?? ""}
              sub={`~ ${result.train_period.split(" to ")[1]?.slice(0, 10) ?? ""}`}
            />
            <MetricCard
              label="검증 기간"
              value={result.val_period.split(" to ")[0]?.slice(0, 10) ?? ""}
              sub={`~ ${result.val_period.split(" to ")[1]?.slice(0, 10) ?? ""}`}
            />
          </div>

          {/* Best Parameters card */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
            <p className="text-sm font-medium text-slate-400 mb-3">
              최적 파라미터
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(result.best_params).map(([name, value]) => (
                <div
                  key={name}
                  className="bg-[#0f1117] border border-slate-700/50 rounded-lg px-3 py-2"
                >
                  <p className="text-xs text-slate-500">{name}</p>
                  <p className="text-lg font-bold text-blue-400">
                    {Number.isInteger(value) ? value : value.toFixed(4)}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Train vs Validation comparison */}
          {comparisonData.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-3">
                학습 vs 검증 (최고 시도)
              </p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={comparisonData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    axisLine={{ stroke: "#334155" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={50}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                    labelStyle={{ color: "#94a3b8" }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }}
                  />
                  <Bar dataKey="학습" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="검증" fill="#22c55e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Convergence chart */}
          {convergenceData.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-3">
                수렴 곡선 (반복에 따른 최고 점수)
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={convergenceData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="trial"
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    axisLine={{ stroke: "#334155" }}
                    tickLine={false}
                    label={{ value: "시도", position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 10 }}
                  />
                  <YAxis
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                    labelStyle={{ color: "#94a3b8" }}
                    formatter={(value: number, name: string) => [
                      value.toFixed(4),
                      name === "bestSoFar" ? "현재 최고" : "시도 점수",
                    ]}
                    labelFormatter={(label) => `시도 ${label}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#475569"
                    strokeWidth={1}
                    dot={{ r: 2, fill: "#475569" }}
                    name="score"
                  />
                  <Line
                    type="stepAfter"
                    dataKey="bestSoFar"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={false}
                    name="bestSoFar"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Top 10 trials table */}
          {top10.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-3">
                상위 10개 시도 (검증 점수 기준)
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="text-left py-2 px-2">순위</th>
                      <th className="text-left py-2 px-2">파라미터</th>
                      <th className="text-right py-2 px-2">학습 Sharpe</th>
                      <th className="text-right py-2 px-2">검증 Sharpe</th>
                      <th className="text-right py-2 px-2">학습 PnL</th>
                      <th className="text-right py-2 px-2">검증 PnL</th>
                      <th className="text-right py-2 px-2">학습 승률</th>
                      <th className="text-right py-2 px-2">검증 승률</th>
                    </tr>
                  </thead>
                  <tbody>
                    {top10.map((t, idx) => (
                      <tr
                        key={t.trial_number}
                        className={`border-b border-slate-800/50 ${idx === 0 ? "bg-green-900/10" : ""}`}
                      >
                        <td className="py-2 px-2 text-slate-400">{idx + 1}</td>
                        <td className="py-2 px-2 text-slate-300 font-mono">
                          {Object.entries(t.params)
                            .map(([k, v]) => `${k}=${Number.isInteger(v) ? v : v.toFixed(2)}`)
                            .join(", ")}
                        </td>
                        <td className="text-right py-2 px-2 text-blue-400">
                          {t.train_sharpe.toFixed(2)}
                        </td>
                        <td className="text-right py-2 px-2 text-green-400">
                          {t.val_sharpe.toFixed(2)}
                        </td>
                        <td className="text-right py-2 px-2 text-blue-400">
                          ${t.train_pnl.toFixed(2)}
                        </td>
                        <td className="text-right py-2 px-2 text-green-400">
                          ${t.val_pnl.toFixed(2)}
                        </td>
                        <td className="text-right py-2 px-2 text-blue-400">
                          {(t.train_win_rate * 100).toFixed(1)}%
                        </td>
                        <td className="text-right py-2 px-2 text-green-400">
                          {(t.val_win_rate * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
