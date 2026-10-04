import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getAccountBalance, getHealth, getPnl, getPositions, getRiskStatus, getTrades } from "@/lib/api";
import type { AccountBalance, HealthStatus, PnlSummary, Position, RiskStatus, Trade } from "@/lib/types";
import { deltaClass, fmtTime, fmtUsd } from "@/lib/format";
import PnlChart from "@/components/PnlChart";
import PositionTable from "@/components/PositionTable";
import { Badge, Card, Delta, PageHeader, StatusDot } from "@/components/ui";

const EMPTY_PNL: PnlSummary = { realized_pnl: 0, win_rate: 0, trade_count: 0, today_pnl: 0 };
const REFRESH_MS = 5_000;

function WinRateRing({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const r = 26;
  const c = 2 * Math.PI * r;
  const good = rate >= 0.5;
  return (
    <div className="relative w-16 h-16 shrink-0">
      <svg width={64} height={64} className="-rotate-90">
        <circle cx={32} cy={32} r={r} fill="none" stroke="var(--color-line)" strokeWidth={6} />
        <circle
          cx={32}
          cy={32}
          r={r}
          fill="none"
          stroke={good ? "var(--color-primary)" : "var(--color-ink-disabled)"}
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (pct / 100) * c}
          style={{ transition: "stroke-dashoffset .6s ease" }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-ink tabular">{pct}%</span>
    </div>
  );
}

function HealthRow({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-line last:border-0">
      <span className="text-sm text-ink-muted">{label}</span>
      <span className="inline-flex items-center gap-2 text-sm font-semibold text-ink-secondary">
        <StatusDot ok={ok} />
        {value}
      </span>
    </div>
  );
}

export default function OverviewPage() {
  const [pnl, setPnl] = useState<PnlSummary>(EMPTY_PNL);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [balance, setBalance] = useState<AccountBalance | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const [p, pos, t, h, r, b] = await Promise.allSettled([
      getPnl("live"),
      getPositions(),
      getTrades({ source: "live", limit: 200 }),
      getHealth(),
      getRiskStatus(),
      getAccountBalance(),
    ]);
    if (p.status === "fulfilled") setPnl(p.value);
    if (pos.status === "fulfilled") setPositions(pos.value);
    if (t.status === "fulfilled") setTrades(t.value);
    if (h.status === "fulfilled") setHealth(h.value);
    if (r.status === "fulfilled") setRisk(r.value);
    if (b.status === "fulfilled") setBalance(b.value);
    setLastUpdated(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const equity = balance?.usdt_equity ?? 0;
  const available = balance?.usdt_available ?? 0;
  const todayPct = equity > 0 ? (pnl.today_pnl / (equity - pnl.today_pnl)) * 100 : null;
  const tripped = risk?.kill_switch.tripped ?? false;

  return (
    <div className="space-y-8">
      <PageHeader
        title="홈"
        sub={lastUpdated ? `${fmtTime(lastUpdated.toISOString())} 갱신 · 5초마다 자동` : "동기화 중…"}
      />

      {/* 내 투자 — 토스 자산 헤더 */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-surface border border-line rounded-xl shadow-card p-6">
          <div className="flex items-center justify-between">
            <p className="text-base font-medium text-ink-muted">계좌 자산 (USDT)</p>
            {health && <Badge tone={health.okx_api.mode === "live" ? "orange" : "blue"}>{health.okx_api.mode === "live" ? "실거래 계좌" : "데모 계좌"}</Badge>}
          </div>
          <p className="mt-2 text-4xl font-bold text-ink tabular tracking-tight">{fmtUsd(equity)}</p>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <span className="text-sm text-ink-muted">오늘</span>
            <Delta abs={pnl.today_pnl} pct={todayPct} size="base" />
            <span className="text-ink-disabled">·</span>
            <span className="text-sm text-ink-muted">
              주문 가능 <span className="font-semibold text-ink-secondary tabular">{fmtUsd(available)}</span>
            </span>
          </div>

          <div className="mt-6 grid grid-cols-3 gap-4 pt-5 border-t border-line">
            <div>
              <p className="text-sm text-ink-muted">누적 실현 손익</p>
              <p className={`mt-1 text-xl font-bold tabular ${deltaClass(pnl.realized_pnl)}`}>{fmtUsd(pnl.realized_pnl, { sign: true })}</p>
            </div>
            <div>
              <p className="text-sm text-ink-muted">열린 포지션</p>
              <p className="mt-1 text-xl font-bold text-ink tabular">{positions.length}<span className="text-base text-ink-muted font-medium ml-0.5">개</span></p>
            </div>
            <div className="flex items-center gap-3">
              <WinRateRing rate={pnl.win_rate} />
              <div>
                <p className="text-sm text-ink-muted">승률</p>
                <p className="text-sm text-ink-secondary mt-0.5">{pnl.trade_count}건 청산</p>
              </div>
            </div>
          </div>
        </div>

        {/* 안전장치 요약 */}
        <div className={`rounded-xl border shadow-card p-6 flex flex-col ${tripped ? "bg-danger-soft border-line" : "bg-surface border-line"}`}>
          <div className="flex items-center justify-between">
            <p className="text-base font-medium text-ink-muted">안전장치</p>
            <Link to="/config" className="text-sm font-semibold text-primary hover:text-primary-hover">
              관리 &gt;
            </Link>
          </div>
          <div className="mt-3 flex items-center gap-2.5">
            <StatusDot ok={!tripped} pulse={tripped} />
            <p className={`text-xl font-bold ${tripped ? "text-danger-strong" : "text-ink"}`}>
              {risk === null ? "연결 중" : tripped ? "긴급 정지 중" : "정상 가동"}
            </p>
          </div>
          {tripped && risk?.kill_switch.reason && (
            <p className="mt-1 text-sm text-danger-strong/80">{risk.kill_switch.reason}</p>
          )}
          <div className="mt-5">
            <HealthRow label="데이터베이스" ok={health?.db === "ok"} value={health?.db ?? "-"} />
            <HealthRow label="OKX API" ok={health?.okx_api.status === "ok"} value={health?.okx_api.status ?? "-"} />
            <HealthRow label="일일 손실 한도" ok={true} value={risk ? fmtUsd(risk.limits.max_daily_loss_usd ?? 0, { digits: 0 }) : "-"} />
          </div>
        </div>
      </section>

      <Card
        title="누적 실현 손익"
        sub="청산된 실거래 기준 · 수수료 반영"
        action={
          <span className={`text-xl font-bold tabular ${deltaClass(pnl.realized_pnl)}`}>
            {fmtUsd(pnl.realized_pnl, { sign: true })}
          </span>
        }
      >
        <PnlChart trades={trades} />
      </Card>

      <Card title="열린 포지션" sub={`${positions.length}개 보유 중`}>
        <PositionTable positions={positions} />
      </Card>
    </div>
  );
}
