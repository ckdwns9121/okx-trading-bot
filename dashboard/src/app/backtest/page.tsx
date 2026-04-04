"use client";

import { useState, useEffect } from "react";
import {
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { runBacktest, getStrategies, getBacktestAnalytics, runMonteCarlo } from "@/lib/api";
import type {
  BacktestParams,
  BacktestRunWithTrades,
  Trade,
  TradeAnalytics,
  MonteCarloResult,
} from "@/lib/types";
import BacktestForm from "@/components/BacktestForm";
import PnlChart from "@/components/PnlChart";
import TradeTable from "@/components/TradeTable";

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

function SmallMetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-[#0f1320] border border-slate-800 rounded-lg p-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-base font-semibold ${color ?? "text-white"}`}>{value}</p>
    </div>
  );
}

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<BacktestRunWithTrades | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);

  const [analytics, setAnalytics] = useState<TradeAnalytics | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);

  const [monteCarlo, setMonteCarlo] = useState<MonteCarloResult | null>(null);
  const [monteCarloLoading, setMonteCarloLoading] = useState(false);
  const [monteCarloError, setMonteCarloError] = useState<string | null>(null);

  useEffect(() => {
    getStrategies()
      .then(setStrategies)
      .catch(() => setStrategies([]));
  }, []);

  async function handleSubmit(params: BacktestParams) {
    setLoading(true);
    setError(null);
    setRun(null);
    setTrades([]);
    setAnalytics(null);
    setMonteCarlo(null);
    try {
      const result = await runBacktest(params);
      setRun(result);
      setTrades(result.trades || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "백테스트 실패");
    } finally {
      setLoading(false);
    }
  }

  async function handleFetchAnalytics() {
    if (!run) return;
    setAnalyticsLoading(true);
    setAnalyticsError(null);
    try {
      const data = await getBacktestAnalytics(String(run.id));
      setAnalytics(data);
    } catch (err) {
      setAnalyticsError(err instanceof Error ? err.message : "분석 로드 실패");
    } finally {
      setAnalyticsLoading(false);
    }
  }

  async function handleRunMonteCarlo() {
    if (!run) return;
    setMonteCarloLoading(true);
    setMonteCarloError(null);
    try {
      const data = await runMonteCarlo(String(run.id));
      setMonteCarlo(data);
    } catch (err) {
      setMonteCarloError(err instanceof Error ? err.message : "몬테카를로 실행 실패");
    } finally {
      setMonteCarloLoading(false);
    }
  }

  const winRateColor =
    run && run.win_rate >= 0.5 ? "text-green-400" : "text-red-400";
  const pnlColor =
    run && run.total_pnl >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">백테스트</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          과거 데이터로 전략 성과를 시뮬레이션합니다
        </p>
      </div>

      {/* Warning banner */}
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
          백테스트는 펀딩 비율 또는 청산을 시뮬레이션하지 않습니다. 결과는
          참고용이며 실제 라이브 성과와 다를 수 있습니다.
        </p>
      </div>

      {/* Form card */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6">
        <h2 className="text-sm font-semibold text-white mb-4">설정</h2>
        <BacktestForm
          strategies={strategies}
          loading={loading}
          onSubmit={handleSubmit}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-xl px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {run && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            결과 — {run.strategy_name} · {run.pair} · {run.timeframe}
          </h2>

          {/* Metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="총 손익"
              value={`${run.total_pnl >= 0 ? "+" : ""}$${run.total_pnl.toFixed(2)}`}
              sub={`초기 자본 $${run.initial_balance.toLocaleString()}`}
              color={pnlColor}
            />
            <MetricCard
              label="승률"
              value={`${(run.win_rate * 100).toFixed(1)}%`}
              sub={`${run.trade_count}건 거래`}
              color={winRateColor}
            />
            <MetricCard
              label="최대 낙폭"
              value={`${(run.max_drawdown * 100).toFixed(1)}%`}
              color={run.max_drawdown > 0.2 ? "text-red-400" : "text-white"}
            />
            <MetricCard
              label="Sharpe 비율"
              value={
                run.sharpe_ratio !== null
                  ? run.sharpe_ratio.toFixed(2)
                  : "N/A"
              }
              color={
                run.sharpe_ratio !== null && run.sharpe_ratio >= 1
                  ? "text-green-400"
                  : "text-slate-300"
              }
            />
          </div>

          {/* Buy & Hold Comparison */}
          {run.buy_hold_pnl != null && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                전략 vs 매수 후 보유
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-slate-500 mb-1">전략 손익</div>
                  <div
                    className={`text-2xl font-bold ${run.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    {run.total_pnl >= 0 ? "+" : ""}${run.total_pnl.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">매수 후 보유 손익</div>
                  <div
                    className={`text-2xl font-bold ${run.buy_hold_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    {run.buy_hold_pnl >= 0 ? "+" : ""}${run.buy_hold_pnl.toFixed(2)}
                  </div>
                  {run.buy_hold_return_pct != null && (
                    <div className="text-xs text-slate-500 mt-0.5">
                      {run.buy_hold_return_pct >= 0 ? "+" : ""}
                      {run.buy_hold_return_pct.toFixed(2)}%
                    </div>
                  )}
                </div>
              </div>
              {/* Outperformance indicator */}
              <div className="mt-3 pt-3 border-t border-slate-800">
                {run.total_pnl > run.buy_hold_pnl ? (
                  <p className="text-xs text-green-400">
                    전략이 매수 후 보유 대비{" "}
                    <span className="font-semibold">
                      ${(run.total_pnl - run.buy_hold_pnl).toFixed(2)}
                    </span>{" "}
                    초과 수익
                  </p>
                ) : (
                  <p className="text-xs text-red-400">
                    전략이 매수 후 보유 대비{" "}
                    <span className="font-semibold">
                      ${(run.buy_hold_pnl - run.total_pnl).toFixed(2)}
                    </span>{" "}
                    미달
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Equity Curve */}
          {run.equity_curve && run.equity_curve.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                자산 곡선
              </h3>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={run.equity_curve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                  <XAxis dataKey="index" stroke="#64748b" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#161b27",
                      border: "1px solid #1e293b",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, "잔고"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="balance"
                    stroke="#10B981"
                    fill="#10B98120"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>

              <h3 className="text-sm font-semibold text-slate-300 mb-3 mt-5">
                낙폭
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={run.equity_curve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                  <XAxis dataKey="index" stroke="#64748b" tick={{ fontSize: 11 }} />
                  <YAxis
                    stroke="#64748b"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#161b27",
                      border: "1px solid #1e293b",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                    formatter={(v: number) => [
                      `${(v * 100).toFixed(2)}%`,
                      "낙폭",
                    ]}
                  />
                  <Area
                    type="monotone"
                    dataKey="drawdown"
                    stroke="#EF4444"
                    fill="#EF444420"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Analytics section */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-300">
                거래 분석
              </h3>
              {!analytics && (
                <button
                  onClick={handleFetchAnalytics}
                  disabled={analyticsLoading}
                  className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-white transition-colors"
                >
                  {analyticsLoading ? "로딩 중…" : "분석 보기"}
                </button>
              )}
            </div>

            {analyticsError && (
              <p className="text-xs text-red-400">{analyticsError}</p>
            )}

            {analytics && (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                <SmallMetricCard
                  label="수익 팩터"
                  value={analytics.profit_factor != null ? analytics.profit_factor.toFixed(2) : "N/A"}
                  color={
                    analytics.profit_factor != null && analytics.profit_factor >= 1.5
                      ? "text-green-400"
                      : "text-slate-300"
                  }
                />
                <SmallMetricCard
                  label="기대값"
                  value={`$${analytics.expectancy.toFixed(2)}`}
                  color={analytics.expectancy >= 0 ? "text-green-400" : "text-red-400"}
                />
                <SmallMetricCard
                  label="페이오프 비율"
                  value={analytics.payoff_ratio != null ? analytics.payoff_ratio.toFixed(2) : "N/A"}
                />
                <SmallMetricCard
                  label="평균 수익 거래"
                  value={`$${analytics.avg_win.toFixed(2)}`}
                  color="text-green-400"
                />
                <SmallMetricCard
                  label="평균 손실 거래"
                  value={`$${analytics.avg_loss.toFixed(2)}`}
                  color="text-red-400"
                />
                <SmallMetricCard
                  label="최고 거래"
                  value={`$${analytics.best_trade_pnl.toFixed(2)}`}
                  color="text-green-400"
                />
                <SmallMetricCard
                  label="최악 거래"
                  value={`$${analytics.worst_trade_pnl.toFixed(2)}`}
                  color="text-red-400"
                />
                <SmallMetricCard
                  label="평균 보유 시간"
                  value={`${analytics.avg_hold_time_minutes.toFixed(0)}분`}
                />
                <SmallMetricCard
                  label="최대 연승"
                  value={String(analytics.max_consecutive_wins)}
                  color="text-green-400"
                />
                <SmallMetricCard
                  label="최대 연패"
                  value={String(analytics.max_consecutive_losses)}
                  color="text-red-400"
                />
                <SmallMetricCard
                  label="수익 거래"
                  value={String(analytics.winning_trades)}
                  color="text-green-400"
                />
                <SmallMetricCard
                  label="손실 거래"
                  value={String(analytics.losing_trades)}
                  color="text-red-400"
                />
              </div>
            )}

            {!analytics && !analyticsLoading && !analyticsError && (
              <p className="text-xs text-slate-600">
                버튼을 눌러 상세 거래 통계를 불러오세요.
              </p>
            )}
          </div>

          {/* Monte Carlo section */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-300">
                몬테카를로 시뮬레이션
              </h3>
              {!monteCarlo && (
                <button
                  onClick={handleRunMonteCarlo}
                  disabled={monteCarloLoading}
                  className="text-xs px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded-lg text-white transition-colors"
                >
                  {monteCarloLoading ? "실행 중…" : "몬테카를로 실행"}
                </button>
              )}
            </div>

            {monteCarloError && (
              <p className="text-xs text-red-400">{monteCarloError}</p>
            )}

            {monteCarlo && (
              <div className="space-y-3">
                <p className="text-xs text-slate-500">
                  {monteCarlo.n_simulations.toLocaleString()}회 시뮬레이션 기준
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <SmallMetricCard
                    label="중간값 최종 잔고"
                    value={`$${monteCarlo.median_final_balance.toFixed(2)}`}
                    color={
                      monteCarlo.median_final_balance >= run.initial_balance
                        ? "text-green-400"
                        : "text-red-400"
                    }
                  />
                  <SmallMetricCard
                    label="5th 백분위 잔고"
                    value={`$${monteCarlo.p5_final_balance.toFixed(2)}`}
                    color="text-red-400"
                  />
                  <SmallMetricCard
                    label="95th 백분위 잔고"
                    value={`$${monteCarlo.p95_final_balance.toFixed(2)}`}
                    color="text-green-400"
                  />
                  <SmallMetricCard
                    label="중간값 최대 낙폭"
                    value={`${(monteCarlo.median_max_drawdown * 100).toFixed(1)}%`}
                    color={
                      monteCarlo.median_max_drawdown > 0.2
                        ? "text-red-400"
                        : "text-slate-300"
                    }
                  />
                  <SmallMetricCard
                    label="95th 최대 낙폭"
                    value={`${(monteCarlo.p95_max_drawdown * 100).toFixed(1)}%`}
                    color="text-red-400"
                  />
                  <SmallMetricCard
                    label="파산 확률"
                    value={`${(monteCarlo.ruin_probability * 100).toFixed(2)}%`}
                    color={
                      monteCarlo.ruin_probability > 0.05
                        ? "text-red-400"
                        : "text-green-400"
                    }
                  />
                </div>
              </div>
            )}

            {!monteCarlo && !monteCarloLoading && !monteCarloError && (
              <p className="text-xs text-slate-600">
                버튼을 눌러 수익 분포의 신뢰 구간을 시뮬레이션하세요.
              </p>
            )}
          </div>

          {/* PnL Chart */}
          {trades.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-3">
                누적 손익
              </p>
              <PnlChart trades={trades} />
            </div>
          )}

          {/* Trade list */}
          {trades.length > 0 && (
            <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-3">
                거래 목록 ({trades.length})
              </p>
              <TradeTable trades={trades} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
