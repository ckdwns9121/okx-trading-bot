import { useEffect, useState } from "react";
import { getDonchianTrader, getMarkets } from "@/lib/api";
import type { DonchianTraderStatus } from "@/lib/types";
import { deltaClass, fmtDateTime, fmtPrice, fmtUsd } from "@/lib/format";
import { Badge, Card, Empty, Skeleton, StatusDot, Td, Th } from "@/components/ui";

const REFRESH_MS = 10_000;

function ago(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 90) return "방금";
  if (seconds < 3600) return `${Math.round(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}시간 전`;
  return `${Math.round(seconds / 86400)}일 전`;
}

/** 돈치안 데모 트레이더: 돌고 있는지, 슬리브별로 뭘 들고 있는지, 최근 체결 */
export default function TraderCard({ tripped }: { tripped: boolean }) {
  const [st, setSt] = useState<DonchianTraderStatus | null>(null);
  const [prices, setPrices] = useState<Record<string, number>>({});

  useEffect(() => {
    let alive = true;
    async function load() {
      const [a, m] = await Promise.allSettled([getDonchianTrader(), getMarkets()]);
      if (!alive) return;
      if (a.status === "fulfilled") setSt(a.value);
      if (m.status === "fulfilled") {
        // markets are USDT-SWAP; spot prices are close enough for a status card
        setPrices(Object.fromEntries(m.value.map((t) => [`${t.symbol}-USDT`, t.price])));
      }
    }
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (!st) {
    return (
      <Card title="자동매매 트레이더" sub="돈치안 돌파 · OKX 데모 현물">
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }
  if (st.status === "not_started") {
    return (
      <Card title="자동매매 트레이더" sub="돈치안 돌파 · OKX 데모 현물">
        <Empty title="트레이더가 아직 시작되지 않았어요" sub="docker compose up -d donchian-trader 로 시작합니다" className="py-8" />
      </Card>
    );
  }

  const sleeves = Object.values(st.sleeves ?? {});
  const capital = st.config?.capital_usd ?? 0;
  const equity = sleeves.reduce((acc, s) => acc + s.cash_usd + s.qty * (prices[s.inst] ?? s.entry_px ?? 0), 0);
  const pnl = equity - capital;
  const running = st.status === "running";
  const tone = !running ? "danger" : tripped ? "warn" : "ok";
  const box = { ok: "bg-ok-soft text-ok-strong", warn: "bg-warn-soft text-warn-strong", danger: "bg-danger-soft text-danger-strong" }[tone];
  const headline = !running ? "응답 없음 — 마지막 확인 이후 너무 오래 지났어요" : tripped ? "실행 중이지만 긴급 정지로 신규 매수 차단" : "실행 중 · 하루 한 번 일봉 확정 후 판단";

  return (
    <Card
      title="자동매매 트레이더"
      sub={st.strategy ?? "돈치안 돌파 · OKX 데모 현물"}
      action={<Badge tone="blue">데모 계좌</Badge>}
    >
      <div className="space-y-5">
        <div className={`rounded-lg px-5 py-4 flex items-start gap-3 ${box}`}>
          <div className="mt-1.5"><StatusDot ok={tone === "ok"} pulse={tone !== "ok"} /></div>
          <div>
            <p className="text-lg font-bold">{headline}</p>
            <p className="text-sm opacity-80 mt-0.5">
              마지막 확인 {ago(st.age_seconds)} · 대기 주문 {st.pending_orders ?? 0}건 · 시작 {fmtDateTime(st.started_at)}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-surface-muted px-4 py-3">
            <p className="text-sm text-ink-muted">봇 자산</p>
            <p className="mt-0.5 text-xl font-bold text-ink tabular">{fmtUsd(equity, { digits: 0 })}</p>
            <p className={`text-sm font-semibold tabular ${deltaClass(pnl)}`}>{fmtUsd(pnl, { sign: true })} ({capital ? ((pnl / capital) * 100).toFixed(2) : "0.00"}%)</p>
          </div>
          <div className="rounded-lg bg-surface-muted px-4 py-3">
            <p className="text-sm text-ink-muted">실현 손익</p>
            <p className={`mt-0.5 text-xl font-bold tabular ${deltaClass(st.realized_pnl_usd)}`}>{fmtUsd(st.realized_pnl_usd ?? 0, { sign: true })}</p>
            <p className="text-sm text-ink-faint">수수료 {fmtUsd(st.fees_usd ?? 0)}</p>
          </div>
          <div className="rounded-lg bg-surface-muted px-4 py-3">
            <p className="text-sm text-ink-muted">체결</p>
            <p className="mt-0.5 text-xl font-bold text-ink tabular">{st.trade_count ?? 0}<span className="text-sm font-medium text-ink-muted ml-0.5">건</span></p>
            <p className="text-sm text-ink-faint">1년에 몇 번만 매매하는 전략</p>
          </div>
        </div>

        <div className="-mx-6 border-t border-line">
          <table className="w-full">
            <thead>
              <tr className="border-b border-line">
                <Th className="pl-6">종목</Th>
                <Th>상태</Th>
                <Th align="right">보유 수량</Th>
                <Th align="right">평단</Th>
                <Th align="right">평가</Th>
                <Th align="right" className="pr-6">마지막 판단 일봉</Th>
              </tr>
            </thead>
            <tbody>
              {sleeves.map((s) => {
                const px = prices[s.inst];
                const holding = s.qty * (px ?? 0) >= 10;
                const value = s.cash_usd + s.qty * (px ?? s.entry_px ?? 0);
                const bar = st.handled_bar?.[s.inst];
                return (
                  <tr key={s.inst} className="border-b border-line last:border-0">
                    <Td className="pl-6 font-semibold text-ink">{s.inst.split("-")[0]}</Td>
                    <Td>{holding ? <Badge tone="red">보유</Badge> : <Badge tone="grey">현금 대기</Badge>}</Td>
                    <Td align="right" className="text-ink-secondary">{holding ? s.qty.toPrecision(6) : "-"}</Td>
                    <Td align="right" className="text-ink-secondary">{holding && s.entry_px ? fmtPrice(s.entry_px) : "-"}</Td>
                    <Td align="right" className="font-semibold text-ink">{fmtUsd(value, { digits: 0 })}</Td>
                    <Td align="right" className="pr-6 text-sm text-ink-faint">{bar ? new Date(bar).toISOString().slice(0, 10) : "-"}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {st.recent_trades && st.recent_trades.length > 0 && (
          <div>
            <p className="text-sm font-semibold text-ink-secondary mb-2">최근 체결</p>
            <div className="space-y-1.5">
              {st.recent_trades.slice().reverse().slice(0, 6).map((t) => (
                <div key={`${t.inst}-${t.fill_ts}-${t.side}`} className="flex items-center justify-between text-sm">
                  <span className="inline-flex items-center gap-2">
                    <Badge tone={t.side === "buy" ? "red" : "blue"}>{t.side === "buy" ? "매수" : "매도"}</Badge>
                    <span className="font-semibold text-ink">{t.inst.split("-")[0]}</span>
                    <span className="text-ink-faint">{fmtDateTime(new Date(t.fill_ts).toISOString())} · {t.reason}</span>
                  </span>
                  <span className="tabular text-ink-secondary">
                    {fmtPrice(t.avg_px)} · {fmtUsd(t.quote_usd, { digits: 0 })}
                    {t.realized_pnl_usd !== null && <span className={`ml-2 font-semibold ${deltaClass(t.realized_pnl_usd)}`}>{fmtUsd(t.realized_pnl_usd, { sign: true })}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
