"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getConfig,
  getStrategies,
  getTradingStatus,
  getTradingLogs,
  getHealth,
  startTrading,
  stopTrading,
  upsertSingleConfig,
} from "@/lib/api";
import type {
  StrategyConfig,
  PairStatus,
  HealthStatus,
  TradingLogEvent,
} from "@/lib/types";

/* ── helpers ─────────────────────────────────────────────── */

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

const inputCls =
  "w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors";

const TIMEFRAMES = [
  "1m", "3m", "5m", "15m", "30m",
  "1H", "2H", "4H", "6H", "12H",
  "1D",
] as const;

/* ── page ────────────────────────────────────────────────── */

export default function ConfigPage() {
  const [configs, setConfigs] = useState<StrategyConfig[]>([]);
  const [statuses, setStatuses] = useState<PairStatus[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [logs, setLogs] = useState<TradingLogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  // Add-pair form
  const [newPair, setNewPair] = useState("BTC-USDT-SWAP");
  const [newStrategy, setNewStrategy] = useState("");
  const [newTimeframe, setNewTimeframe] = useState<string>("1m");
  const [newLeverage, setNewLeverage] = useState(1);
  const [addingPair, setAddingPair] = useState(false);

  const load = useCallback(async () => {
    const [c, s, st, h, lg] = await Promise.allSettled([
      getConfig(),
      getStrategies(),
      getTradingStatus(),
      getHealth(),
      getTradingLogs(120),
    ]);
    if (c.status === "fulfilled") setConfigs(c.value);
    if (s.status === "fulfilled") {
      setStrategies(s.value);
      setNewStrategy((prev) => prev || s.value[0] || "");
    }
    if (st.status === "fulfilled") setStatuses(st.value);
    if (h.status === "fulfilled") setHealth(h.value);
    if (lg.status === "fulfilled") setLogs(lg.value);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const next = await getTradingLogs(120);
        setLogs(next);
      } catch {
        // keep existing logs on transient fetch errors
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  function flash(msg: string) {
    setActionMsg(msg);
    setTimeout(() => setActionMsg(null), 3000);
  }

  async function handleStart() {
    try {
      await startTrading();
      flash("Trading started.");
      load();
    } catch (e) {
      flash(`Error: ${(e as Error).message}`);
    }
  }

  async function handleStop() {
    try {
      await stopTrading();
      flash("Trading stopped.");
      load();
    } catch (e) {
      flash(`Error: ${(e as Error).message}`);
    }
  }

  async function togglePair(index: number) {
    const target = configs[index];
    const newEnabled = !target.enabled;
    const updated = configs.map((c, i) =>
      i === index ? { ...c, enabled: newEnabled } : c
    );
    setConfigs(updated);
    try {
      await upsertSingleConfig({
        strategy_name: target.strategy_name,
        pair: target.pair,
        timeframe: target.timeframe || "1m",
        parameters_json: target.params ?? null,
        leverage: target.leverage,
        is_active: newEnabled,
      });
      flash("설정 저장됨.");
    } catch (e) {
      flash(`저장 실패: ${(e as Error).message}`);
    }
  }

  async function handleAddPair(e: React.FormEvent) {
    e.preventDefault();
    setAddingPair(true);
    try {
      await upsertSingleConfig({
        strategy_name: newStrategy,
        pair: newPair.toUpperCase(),
        timeframe: newTimeframe,
        parameters_json: {},
        leverage: newLeverage,
        is_active: true,
      });
      setNewPair("BTC-USDT-SWAP");
      setNewTimeframe("1m");
      setNewLeverage(1);
      await load();
      flash("Pair added.");
    } catch (e) {
      flash(`Add failed: ${(e as Error).message}`);
    } finally {
      setAddingPair(false);
    }
  }

  /* running state derived from statuses */
  const activeCount = statuses.filter((s) => s.status === "running").length;
  const isRunning = activeCount > 0;
  const activeByPair = configs.reduce<Record<string, number>>((acc, c) => {
    if (c.enabled) acc[c.pair] = (acc[c.pair] ?? 0) + 1;
    return acc;
  }, {});
  const duplicateActivePairs = Object.entries(activeByPair)
    .filter(([, count]) => count > 1)
    .map(([pair]) => pair);

  const mode = health?.okx_api.mode ?? null;
  const cbStatus = health?.circuit_breaker ?? null;

  function renderLogText(log: TradingLogEvent): string {
    const details = log.details ?? {};
    if (log.event === "pair_signal") {
      const signal = details["signal"];
      const reason = details["reason"];
      if (typeof signal === "string" && typeof reason === "string") {
        return `${signal} · ${reason}`;
      }
    }
    if (typeof log.message === "string" && log.message.trim().length > 0) {
      return log.message;
    }
    if (Object.keys(details).length > 0) {
      return JSON.stringify(details);
    }
    return "-";
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        Loading configuration…
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">Configuration</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Manage trading pairs, strategies, and safety settings
        </p>
      </div>

      {/* Action feedback */}
      {actionMsg && (
        <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg px-4 py-2.5 text-sm text-blue-300">
          {actionMsg}
        </div>
      )}

      {/* ── Mode Warning ──────────────────────────────────── */}
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
            <p className="text-sm font-semibold text-red-400">LIVE MODE ACTIVE</p>
            <p className="text-xs text-red-400/80 mt-0.5">
              Real funds are at risk. All trades will be executed on the live OKX exchange.
              Double-check every setting before starting.
            </p>
          </div>
        </div>
      )}

      {/* ── Section 1: Trading Control ────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="Trading Control"
          sub="Start or stop all active trading pairs"
        />
        <div className="flex items-center gap-4">
          {/* Status indicator */}
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isRunning ? "bg-green-400 animate-pulse" : "bg-slate-600"
              }`}
            />
            <span className="text-sm text-slate-300">
              {isRunning
                ? `Running — ${activeCount} active pair${activeCount !== 1 ? "s" : ""}`
                : "Stopped"}
            </span>
          </div>

          <div className="flex gap-2 ml-auto">
            <button
              onClick={handleStart}
              disabled={isRunning}
              className="px-4 py-2 bg-green-700 hover:bg-green-600 disabled:bg-slate-700
                         disabled:text-slate-500 text-white text-sm font-medium rounded-lg
                         transition-colors"
            >
              Start
            </button>
            <button
              onClick={handleStop}
              disabled={!isRunning}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 disabled:bg-slate-700
                         disabled:text-slate-500 text-white text-sm font-medium rounded-lg
                         transition-colors"
            >
              Stop
            </button>
          </div>
        </div>

        {/* Per-pair status */}
        {statuses.length > 0 && (
          <div className="mt-4 space-y-2">
            {statuses.map((s) => {
              const colorMap: Record<PairStatus["status"], string> = {
                running: "text-green-400",
                stopped: "text-slate-500",
                error: "text-red-400",
                idle: "text-slate-400",
                unknown: "text-yellow-400",
              };
              return (
                <div
                  key={`${s.pair}-${s.strategy_name}`}
                  className="flex items-center justify-between text-xs text-slate-400 border-t border-slate-800/60 pt-2"
                >
                  <span className="font-medium text-slate-300">{s.pair}</span>
                  <span className="text-slate-500">
                    {s.strategy_name} · {s.timeframe ?? "1m"}
                  </span>
                  <span className={colorMap[s.status]}>{s.status}</span>
                  {s.error && (
                    <span className="text-red-400 truncate max-w-[220px]">
                      {s.error}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Section: Live Logs ───────────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="Live Logs"
          sub="Signals, orders, and runtime events (auto-refresh every 5s)"
        />
        {logs.length === 0 ? (
          <p className="text-sm text-slate-500">No runtime logs yet.</p>
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
                            · {[log.pair, log.strategy, log.timeframe].filter(Boolean).join(" / ")}
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

      {/* ── Section 2: Active Pairs ───────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="Active Pairs"
          sub="Toggle pairs on/off without removing them"
        />
        {duplicateActivePairs.length > 0 && (
          <div className="mb-3 rounded-lg border border-amber-700/50 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
            같은 Pair에 여러 전략이 활성화되어 있음: {duplicateActivePairs.join(", ")}.
            현재 엔진은 Pair당 1개 전략만 실행되므로 하나만 활성화하는 것을 권장.
          </div>
        )}
        {configs.length === 0 ? (
          <p className="text-sm text-slate-500">No pairs configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
                  <th className="pb-3 pr-4 font-medium">Pair</th>
                  <th className="pb-3 pr-4 font-medium">Strategy</th>
                  <th className="pb-3 pr-4 font-medium">TF</th>
                  <th className="pb-3 pr-4 font-medium">Lev</th>
                  <th className="pb-3 font-medium">Enabled</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {configs.map((c, i) => (
                  <tr key={`${c.pair}-${c.strategy_name}`} className="hover:bg-slate-800/20">
                    <td className="py-3 pr-4 font-medium text-white">{c.pair}</td>
                    <td className="py-3 pr-4 text-slate-400 text-xs">{c.strategy_name}</td>
                    <td className="py-3 pr-4 text-slate-400">{c.timeframe}</td>
                    <td className="py-3 pr-4 text-slate-400">{c.leverage}x</td>
                    <td className="py-3">
                      <button
                        onClick={() => togglePair(i)}
                        className={`relative w-10 h-5 rounded-full transition-colors ${
                          c.enabled ? "bg-blue-600" : "bg-slate-700"
                        }`}
                        aria-label={c.enabled ? "Disable" : "Enable"}
                      >
                        <span
                          className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-all ${
                            c.enabled ? "left-5" : "left-0.5"
                          }`}
                        />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Section 3: Add Pair ───────────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader title="Add Pair" sub="Add a new trading pair to the bot" />
        <form onSubmit={handleAddPair} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Pair</label>
              <input
                type="text"
                value={newPair}
                onChange={(e) => setNewPair(e.target.value.toUpperCase())}
                placeholder="BTC-USDT-SWAP"
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Strategy</label>
              <select
                value={newStrategy}
                onChange={(e) => setNewStrategy(e.target.value)}
                className={inputCls}
                required
              >
                {strategies.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Timeframe</label>
              <select
                value={newTimeframe}
                onChange={(e) => setNewTimeframe(e.target.value)}
                className={inputCls}
                required
              >
                {TIMEFRAMES.map((tf) => (
                  <option key={tf} value={tf}>{tf}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Leverage: <span className="text-white font-semibold">{newLeverage}x</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                value={newLeverage}
                onChange={(e) => setNewLeverage(Number(e.target.value))}
                className="w-full accent-blue-500 mt-2"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={addingPair || strategies.length === 0}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700
                       disabled:text-slate-500 text-white text-sm font-medium rounded-lg
                       transition-colors"
          >
            {addingPair ? "Adding…" : "Add Pair"}
          </button>
        </form>
      </div>

      {/* ── Section 4: Safety Settings ────────────────────── */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <SectionHeader
          title="Safety Settings"
          sub="Circuit breaker and risk limits"
        />
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <span className="text-slate-400">Circuit Breaker</span>
            <span
              className={`font-semibold ${
                cbStatus === "closed"
                  ? "text-green-400"
                  : cbStatus === "open"
                  ? "text-red-400"
                  : "text-yellow-400"
              }`}
            >
              {cbStatus ?? "—"}
            </span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <span className="text-slate-400">Mode</span>
            <span
              className={`font-semibold ${
                mode === "live" ? "text-orange-400" : "text-blue-400"
              }`}
            >
              {mode?.toUpperCase() ?? "—"}
            </span>
          </div>
          {health && (
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">Failed Tasks</span>
              <span
                className={
                  health.trading_tasks.failed > 0 ? "text-red-400 font-semibold" : "text-slate-300"
                }
              >
                {health.trading_tasks.failed}
              </span>
            </div>
          )}
          {cbStatus === "open" && (
            <div className="mt-3 p-3 bg-red-900/20 border border-red-800/50 rounded-lg text-xs text-red-400">
              Circuit breaker is OPEN — trading is halted due to excessive losses.
              Investigate before resetting.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
