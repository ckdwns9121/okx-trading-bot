"use client";

import { useState } from "react";
import type { BacktestParams } from "@/lib/types";

interface Props {
  strategies: string[];
  loading: boolean;
  onSubmit: (params: BacktestParams) => void;
}

const TIMEFRAMES = ["1m", "5m", "15m", "1H", "4H", "1D"] as const;

const DEFAULT_END = new Date().toISOString().split("T")[0];
const DEFAULT_START = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000)
  .toISOString()
  .split("T")[0];

export default function BacktestForm({ strategies, loading, onSubmit }: Props) {
  const [strategy, setStrategy] = useState(strategies[0] ?? "");
  const [pair, setPair] = useState("BTC-USDT-SWAP");
  const [timeframe, setTimeframe] = useState<string>("1H");
  const [startDate, setStartDate] = useState(DEFAULT_START);
  const [endDate, setEndDate] = useState(DEFAULT_END);
  const [initialBalance, setInitialBalance] = useState(10000);
  const [leverage, setLeverage] = useState(1);
  const [feeRate, setFeeRate] = useState(0.0005);
  const [slippage, setSlippage] = useState(0.001);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      strategy_name: strategy,
      pair,
      timeframe,
      start_date: startDate,
      end_date: endDate,
      initial_balance: initialBalance,
      leverage,
      fee_rate: feeRate,
      slippage_pct: slippage,
    });
  }

  const inputCls =
    "w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors";
  const labelCls = "block text-xs font-medium text-slate-400 mb-1.5";

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        {/* Strategy */}
        <div>
          <label className={labelCls}>전략</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className={inputCls}
            required
          >
            {strategies.length === 0 && (
              <option value="">사용 가능한 전략 없음</option>
            )}
            {strategies.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Pair */}
        <div>
          <label className={labelCls}>거래쌍</label>
          <input
            type="text"
            value={pair}
            onChange={(e) => setPair(e.target.value.toUpperCase())}
            placeholder="BTC-USDT-SWAP"
            className={inputCls}
            required
          />
        </div>

        {/* Timeframe */}
        <div>
          <label className={labelCls}>타임프레임</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className={inputCls}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>

        {/* Initial Balance */}
        <div>
          <label className={labelCls}>초기 잔고 (USD)</label>
          <input
            type="number"
            value={initialBalance}
            onChange={(e) => setInitialBalance(Number(e.target.value))}
            min={100}
            step={100}
            className={inputCls}
            required
          />
        </div>

        {/* Start Date */}
        <div>
          <label className={labelCls}>시작일</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={inputCls}
            required
          />
        </div>

        {/* End Date */}
        <div>
          <label className={labelCls}>종료일</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className={inputCls}
            required
          />
        </div>

        {/* Fee Rate */}
        <div>
          <label className={labelCls}>수수료율 (예: 0.0005 = 0.05%)</label>
          <input
            type="number"
            value={feeRate}
            onChange={(e) => setFeeRate(Number(e.target.value))}
            min={0}
            max={0.01}
            step={0.0001}
            className={inputCls}
          />
        </div>

        {/* Slippage */}
        <div>
          <label className={labelCls}>슬리피지 % (예: 0.001 = 0.1%)</label>
          <input
            type="number"
            value={slippage}
            onChange={(e) => setSlippage(Number(e.target.value))}
            min={0}
            max={0.05}
            step={0.001}
            className={inputCls}
          />
        </div>
      </div>

      {/* Leverage slider — full width */}
      <div>
        <label className={labelCls}>
          레버리지: <span className="text-white font-semibold">{leverage}x</span>
        </label>
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={leverage}
          onChange={(e) => setLeverage(Number(e.target.value))}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-xs text-slate-600 mt-1">
          {[1, 2, 3, 4, 5].map((v) => (
            <span key={v}>{v}x</span>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={loading || strategies.length === 0}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500
                   text-white font-semibold py-2.5 rounded-lg text-sm transition-colors
                   flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
            </svg>
            백테스트 실행 중…
          </>
        ) : (
          "백테스트 실행"
        )}
      </button>
    </form>
  );
}
