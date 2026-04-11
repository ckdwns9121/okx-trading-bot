"use client";

import { useState } from "react";
import { getRecommendation } from "@/lib/api";
import type { SelectionResult, StrategyScore } from "@/lib/types";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H", "1D"] as const;

const REGIME_COLORS: Record<string, string> = {
  trending_up: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  trending_down: "bg-red-500/20 text-red-400 border-red-500/40",
  ranging: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  volatile: "bg-purple-500/20 text-purple-400 border-purple-500/40",
};

const REGIME_LABELS: Record<string, string> = {
  trending_up: "상승 추세",
  trending_down: "하락 추세",
  ranging: "횡보",
  volatile: "고변동성",
};

function scoreColor(score: number): string {
  if (score >= 0.7) return "text-emerald-400";
  if (score >= 0.4) return "text-yellow-400";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 0.7) return "bg-emerald-500/20";
  if (score >= 0.4) return "bg-yellow-500/20";
  return "bg-red-500/20";
}

export default function SelectorPage() {
  const [pair, setPair] = useState("BTC-USDT-SWAP");
  const [timeframe, setTimeframe] = useState("1H");
  const [result, setResult] = useState<SelectionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAnalyse() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await getRecommendation({ pair, timeframe });
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "분석 실패");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">전략 선택기</h1>
        <p className="text-sm text-slate-400 mt-1">
          시장 국면을 분석하고 최적의 전략을 추천받으세요
        </p>
      </div>

      {/* Input section */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              거래쌍
            </label>
            <input
              type="text"
              value={pair}
              onChange={(e) => setPair(e.target.value)}
              className="w-full px-3 py-2 bg-[#0f1117] border border-slate-700 rounded-lg text-sm text-white
                         focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              placeholder="BTC-USDT-SWAP"
            />
          </div>
          <div className="w-36">
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              타임프레임
            </label>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="w-full px-3 py-2 bg-[#0f1117] border border-slate-700 rounded-lg text-sm text-white
                         focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
          <button
            onClick={handleAnalyse}
            disabled={loading || !pair.trim()}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500
                       text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? "분석 중..." : "시장 분석"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="bg-[#161b27] border border-slate-800 rounded-xl p-12 flex items-center justify-center">
          <div className="text-slate-400 text-sm">
            시장 국면 감지 및 전략 백테스트 실행 중... 잠시 기다려주세요.
          </div>
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <>
          {/* Regime Display */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 space-y-6">
            <h2 className="text-lg font-semibold text-white">시장 국면</h2>

            <div className="flex flex-wrap items-center gap-6">
              {/* Regime badge */}
              <div
                className={`px-5 py-3 rounded-xl border text-xl font-bold tracking-wide ${
                  REGIME_COLORS[result.regime.regime] || "bg-slate-700 text-slate-300 border-slate-600"
                }`}
              >
                {REGIME_LABELS[result.regime.regime] || result.regime.regime.toUpperCase()}
              </div>

              {/* Confidence */}
              <div className="flex-1 min-w-[200px]">
                <div className="text-xs text-slate-400 mb-1">신뢰도</div>
                <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all duration-500"
                    style={{ width: `${Math.round(result.regime.confidence * 100)}%` }}
                  />
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {(result.regime.confidence * 100).toFixed(1)}%
                </div>
              </div>
            </div>

            {/* Key metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <MetricCard label="ADX" value={result.regime.adx.toFixed(1)} hint="추세 강도" />
              <MetricCard label="변동성" value={`${result.regime.volatility.toFixed(2)}%`} hint="ATR / 가격" />
              <MetricCard
                label="추세 방향"
                value={result.regime.trend_direction > 0 ? "강세" : result.regime.trend_direction < 0 ? "약세" : "중립"}
                hint={`${result.regime.trend_direction > 0 ? "+" : ""}${result.regime.trend_direction.toFixed(2)}`}
                valueColor={result.regime.trend_direction > 0 ? "text-emerald-400" : result.regime.trend_direction < 0 ? "text-red-400" : "text-slate-300"}
              />
              <MetricCard label="BB 폭" value={`${(result.regime.details.bb_width ?? 0).toFixed(2)}%`} hint="밴드 범위" />
            </div>
          </div>

          {/* Recommendation */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 space-y-4">
            <h2 className="text-lg font-semibold text-white">추천</h2>

            <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-2xl font-bold text-blue-400">
                  {result.recommended_strategy}
                </span>
                {result.scores.length > 0 && (
                  <span className="px-2 py-0.5 bg-blue-500/20 text-blue-300 text-xs rounded-full font-medium">
                    점수: {result.scores[0]?.composite_score.toFixed(2)}
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-300 leading-relaxed">
                {result.reasoning}
              </p>
              <a
                href="/config"
                className="inline-block mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                이 전략 적용하기
              </a>
            </div>
          </div>

          {/* Strategy ranking table */}
          <div className="bg-[#161b27] border border-slate-800 rounded-xl p-6 space-y-4">
            <h2 className="text-lg font-semibold text-white">전략 순위</h2>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="text-left py-3 px-3 font-medium">#</th>
                    <th className="text-left py-3 px-3 font-medium">전략</th>
                    <th className="text-right py-3 px-3 font-medium">국면 적합도</th>
                    <th className="text-right py-3 px-3 font-medium">Sharpe</th>
                    <th className="text-right py-3 px-3 font-medium">승률</th>
                    <th className="text-right py-3 px-3 font-medium">손익</th>
                    <th className="text-right py-3 px-3 font-medium">종합 점수</th>
                  </tr>
                </thead>
                <tbody>
                  {result.scores.map((s: StrategyScore, i: number) => {
                    const isRecommended = s.strategy_name === result.recommended_strategy;
                    return (
                      <tr
                        key={s.strategy_name}
                        className={`border-b border-slate-800 transition-colors ${
                          isRecommended
                            ? "bg-blue-500/10"
                            : "hover:bg-slate-800/50"
                        }`}
                      >
                        <td className="py-3 px-3 text-slate-500">{i + 1}</td>
                        <td className="py-3 px-3">
                          <span className={isRecommended ? "text-blue-400 font-semibold" : "text-white"}>
                            {s.strategy_name}
                          </span>
                          {isRecommended && (
                            <span className="ml-2 text-xs text-blue-400">추천</span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${scoreBg(s.regime_fit)} ${scoreColor(s.regime_fit)}`}>
                            {(s.regime_fit * 100).toFixed(0)}%
                          </span>
                        </td>
                        <td className={`py-3 px-3 text-right ${s.sharpe_ratio > 0 ? "text-emerald-400" : s.sharpe_ratio < 0 ? "text-red-400" : "text-slate-400"}`}>
                          {s.sharpe_ratio.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-300">
                          {(s.win_rate * 100).toFixed(1)}%
                        </td>
                        <td className={`py-3 px-3 text-right ${s.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          ${s.total_pnl.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={`font-semibold ${scoreColor(s.composite_score)}`}>
                            {s.composite_score.toFixed(3)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  valueColor = "text-white",
}: {
  label: string;
  value: string;
  hint: string;
  valueColor?: string;
}) {
  return (
    <div className="bg-[#0f1117] border border-slate-800 rounded-lg p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-lg font-semibold ${valueColor}`}>{value}</div>
      <div className="text-xs text-slate-600 mt-0.5">{hint}</div>
    </div>
  );
}
