"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getPnl, getPositions, getTrades, getHealth, getAccountBalance } from "@/lib/api";
import type { AccountBalance, HealthStatus, PnlSummary, Position, Trade } from "@/lib/types";
import PnlChart from "@/components/PnlChart";
import WinRateCard from "@/components/WinRateCard";
import PositionTable from "@/components/PositionTable";

interface Props {
  initialPnl: PnlSummary;
  initialPositions: Position[];
  initialTrades: Trade[];
  initialHealth: HealthStatus | null;
  initialBalance: AccountBalance | null;
}

function StatCard({
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
    <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color ?? "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-600 mt-0.5">{sub}</p>}
    </div>
  );
}

function HealthDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${
        ok ? "bg-green-400" : "bg-red-500"
      }`}
    />
  );
}

function HealthBadge({ health }: { health: HealthStatus | null }) {
  if (!health) {
    return (
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <p className="text-xs text-slate-500 mb-3">봇 상태</p>
        <p className="text-xs text-slate-600">사용 불가</p>
      </div>
    );
  }

  const dbOk = health.db === "ok";
  const apiOk = health.okx_api.status === "ok";

  return (
    <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-slate-500">봇 상태</p>
        <span
          className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
            health.okx_api.mode === "live"
              ? "text-orange-400 border-orange-800 bg-orange-900/30"
              : "text-blue-400 border-blue-800 bg-blue-900/30"
          }`}
        >
          {health.okx_api.mode.toUpperCase()}
        </span>
      </div>
      <ul className="space-y-2 text-xs">
        <li className="flex items-center justify-between">
          <span className="text-slate-400">데이터베이스</span>
          <span className="flex items-center gap-1.5">
            <HealthDot ok={dbOk} />
            <span className={dbOk ? "text-green-400" : "text-red-400"}>
              {health.db}
            </span>
          </span>
        </li>
        <li className="flex items-center justify-between">
          <span className="text-slate-400">OKX API</span>
          <span className="flex items-center gap-1.5">
            <HealthDot ok={apiOk} />
            <span className={apiOk ? "text-green-400" : "text-red-400"}>
              {health.okx_api.status}
            </span>
          </span>
        </li>
        <li className="flex items-center justify-between">
          <span className="text-slate-400">Legacy 서킷브레이커</span>
          <span className="flex items-center gap-1.5">
            <HealthDot ok={health.circuit_breaker === "removed"} />
            <span className="text-slate-400">
              {health.circuit_breaker}
            </span>
          </span>
        </li>
        <li className="flex items-center justify-between border-t border-slate-800 pt-2 mt-1">
          <span className="text-slate-400">활성 작업</span>
          <span className="text-white font-medium">
            {health.trading_tasks.active}
          </span>
        </li>
      </ul>
    </div>
  );
}

export default function OverviewClient({
  initialPnl,
  initialPositions,
  initialTrades,
  initialHealth,
  initialBalance,
}: Props) {
  const [pnl, setPnl] = useState(initialPnl);
  const [positions, setPositions] = useState(initialPositions);
  const [trades, setTrades] = useState(initialTrades);
  const [health, setHealth] = useState(initialHealth);
  const [balance, setBalance] = useState<AccountBalance | null>(initialBalance);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const [p, pos, t, h, b] = await Promise.allSettled([
      getPnl("live"),
      getPositions(),
      getTrades({ source: "live", limit: 100 }),
      getHealth(),
      getAccountBalance(),
    ]);
    if (p.status === "fulfilled") setPnl(p.value);
    if (pos.status === "fulfilled") setPositions(pos.value);
    if (t.status === "fulfilled") setTrades(t.value);
    if (h.status === "fulfilled") setHealth(h.value);
    if (b.status === "fulfilled") setBalance(b.value);
    setLastUpdated(new Date());
  }, []);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    setLastUpdated(new Date());
    intervalRef.current = setInterval(refresh, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh]);

  const pnlColor = pnl.realized_pnl >= 0 ? "text-green-400" : "text-red-400";
  const todayColor = pnl.today_pnl >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">개요</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            실시간 트레이딩 대시보드 · 5초마다 자동 갱신
          </p>
        </div>
        <p className="text-xs text-slate-600">
          {lastUpdated
            ? `갱신됨 ${lastUpdated.toLocaleTimeString("ko-KR")}`
            : "동기화 중…"}
        </p>
      </div>

      {/* 2×2 stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard
          label="계좌 잔고(USDT)"
          value={`$${(balance?.usdt_equity ?? 0).toFixed(2)}`}
          sub={`가용 $${(balance?.usdt_available ?? 0).toFixed(2)}`}
          color="text-cyan-400"
        />
        <StatCard
          label="실현 손익"
          value={`${pnl.realized_pnl >= 0 ? "+" : ""}$${pnl.realized_pnl.toFixed(2)}`}
          sub="누적 전체"
          color={pnlColor}
        />
        <StatCard
          label="오늘 손익"
          value={`${pnl.today_pnl >= 0 ? "+" : ""}$${pnl.today_pnl.toFixed(2)}`}
          sub="자정 UTC 이후"
          color={todayColor}
        />
        <StatCard
          label="열린 포지션"
          value={String(positions.length)}
          sub={`총 ${pnl.trade_count}건 거래`}
        />
        <StatCard
          label="승률"
          value={`${(pnl.win_rate * 100).toFixed(1)}%`}
          sub={`${pnl.trade_count}건 청산 거래`}
          color={pnl.win_rate >= 0.5 ? "text-green-400" : "text-red-400"}
        />
      </div>

      {/* Win Rate card + Health */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <WinRateCard
            win_rate={pnl.win_rate}
            trade_count={pnl.trade_count}
            realized_pnl={pnl.realized_pnl}
          />
        </div>
        <HealthBadge health={health} />
      </div>

      {/* PnL Chart */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <p className="text-sm font-medium text-slate-400 mb-3">
          누적 손익 — 실시간 거래
        </p>
        <PnlChart trades={trades} />
      </div>

      {/* Positions table */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        <p className="text-sm font-medium text-slate-400 mb-4">
          열린 포지션 ({positions.length})
        </p>
        <PositionTable positions={positions} />
      </div>
    </div>
  );
}
