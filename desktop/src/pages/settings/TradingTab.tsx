import { useCallback, useEffect, useState } from "react";
import { getDemoTrader, getHealth, getRiskStatus, resetKillSwitch, tripKillSwitch } from "@/lib/api";
import type { DemoTraderStatus, HealthStatus, RiskStatus } from "@/lib/types";
import { deltaClass, fmtDateTime, fmtInt, fmtPrice, fmtUsd } from "@/lib/format";
import { Badge, Button, Card, Empty, Notice, Skeleton, StatusDot, Td, Th } from "@/components/ui";

const LIMIT_LABELS: Record<string, { label: string; unit: string }> = {
  max_order_notional_usd: { label: "주문당 최대 금액", unit: "USD" },
  max_instrument_notional_usd: { label: "종목당 최대 포지션", unit: "USD" },
  max_total_exposure_usd: { label: "총 노출 한도", unit: "USD" },
  max_price_deviation_pct: { label: "가격 괴리 한도", unit: "%" },
  max_daily_loss_usd: { label: "일일 손실 한도", unit: "USD" },
  max_orders_per_minute: { label: "분당 최대 주문", unit: "건" },
};

const REFRESH_MS = 5_000;

function strategyName(s?: string | null): string {
  if (s === "donchian") return "돈치안 채널 돌파";
  if (s === "ma") return "이동평균 앙상블";
  return s ?? "-";
}

function ageLabel(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 90) return "방금";
  if (seconds < 3600) return `${Math.round(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}시간 전`;
  return `${Math.round(seconds / 86400)}일 전`;
}

/** 데모 트레이더 — "자동매매가 실제로 돌고 있는가"를 한눈에 */
function TraderCard({ demo, tripped }: { demo: DemoTraderStatus | null; tripped: boolean }) {
  if (!demo) {
    return (
      <Card title="자동매매 트레이더" sub="OKX 데모 계좌 · 일봉 추세추종">
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }
  if (demo.status === "not_started") {
    return (
      <Card title="자동매매 트레이더" sub="OKX 데모 계좌 · 일봉 추세추종">
        <Empty title="트레이더가 아직 실행된 적이 없어요" sub="docker compose up 으로 demo-trader 서비스를 올리면 여기에 상태가 표시됩니다" className="py-8" />
      </Card>
    );
  }

  const cfg = demo.config;
  const positions = Object.entries(demo.positions ?? {});
  const blocked = tripped && demo.running;
  const tone: "ok" | "warn" | "danger" = blocked ? "warn" : demo.running ? "ok" : "danger";
  const headline = blocked
    ? "실행 중이지만 킬스위치에 막혀 있어요"
    : demo.running
      ? "실행 중 · 신호를 기다리는 중"
      : "응답 없음 · 마지막 평가 이후 너무 오래 지났어요";
  const toneCls = {
    ok: { box: "bg-ok-soft", text: "text-ok-strong" },
    warn: { box: "bg-warn-soft", text: "text-warn-strong" },
    danger: { box: "bg-danger-soft", text: "text-danger-strong" },
  }[tone];

  return (
    <Card
      title="자동매매 트레이더"
      sub={demo.strategy ?? "OKX 데모 트레이더"}
      action={cfg && <Badge tone={cfg.mode === "live" ? "orange" : "blue"}>{cfg.mode === "live" ? "실거래" : "데모 계좌"}</Badge>}
    >
      <div className="space-y-5">
        <div className={`rounded-lg px-5 py-4 flex items-start gap-3 ${toneCls.box}`}>
          <div className="mt-1.5">
            <StatusDot ok={tone === "ok"} pulse={tone !== "ok"} />
          </div>
          <div className="min-w-0 flex-1">
            <p className={`text-lg font-bold ${toneCls.text}`}>{headline}</p>
            <p className={`text-sm mt-0.5 ${toneCls.text} opacity-80`}>
              마지막 평가 {ageLabel(demo.age_seconds)} · {fmtDateTime(demo.last_loop_at)}
              {cfg && ` · ${Math.round(cfg.poll_seconds / 60)}분마다 평가`}
            </p>
          </div>
        </div>

        {cfg ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg bg-surface-muted px-4 py-3">
              <p className="text-sm text-ink-muted">전략</p>
              <p className="mt-0.5 text-base font-bold text-ink">{strategyName(cfg.strategy)}</p>
              <p className="text-xs text-ink-faint mt-0.5 tabular">
                {cfg.strategy === "donchian"
                  ? `진입 ${cfg.donchian.entry_period}일 · 청산 ${cfg.donchian.exit_period}일 · ATR×${cfg.donchian.atr_stop_mult ?? "-"}`
                  : `MA ${cfg.ma_periods.join("/")}`}
              </p>
            </div>
            <div className="rounded-lg bg-surface-muted px-4 py-3">
              <p className="text-sm text-ink-muted">종목</p>
              <p className="mt-0.5 text-base font-bold text-ink">{cfg.pairs.map((p) => p.replace("-USDT-SWAP", "")).join(", ")}</p>
              <p className="text-xs text-ink-faint mt-0.5">무기한 선물 · 롱/현금만</p>
            </div>
            <div className="rounded-lg bg-surface-muted px-4 py-3">
              <p className="text-sm text-ink-muted">종목당 목표 금액</p>
              <p className="mt-0.5 text-base font-bold text-ink tabular">{fmtUsd(cfg.allocation_usd, { digits: 0 })}</p>
              <p className="text-xs text-ink-faint mt-0.5">최소 주문 {fmtUsd(cfg.min_trade_usd, { digits: 0 })}</p>
            </div>
            <div className={`rounded-lg px-4 py-3 ${cfg.leverage > 1 ? "bg-warn-soft" : "bg-surface-muted"}`}>
              <p className={`text-sm ${cfg.leverage > 1 ? "text-warn-strong" : "text-ink-muted"}`}>레버리지</p>
              <p className={`mt-0.5 text-base font-bold tabular ${cfg.leverage > 1 ? "text-warn-strong" : "text-ink"}`}>{cfg.leverage}배</p>
              <p className={`text-xs mt-0.5 ${cfg.leverage > 1 ? "text-warn-strong opacity-80" : "text-ink-faint"}`}>
                {cfg.leverage > 1 ? "1배 백테스트 근거가 무효화됨" : "백테스트와 동일"}
              </p>
            </div>
          </div>
        ) : (
          <Notice tone="blue" title="설정 정보가 아직 기록되지 않았어요">
            트레이더를 한 번 재시작하면 전략·종목·레버리지가 여기에 표시됩니다.
          </Notice>
        )}

        <div className="grid grid-cols-3 gap-3">
          <div>
            <p className="text-sm text-ink-muted">체결</p>
            <p className="mt-0.5 text-xl font-bold text-ink tabular">{demo.trade_count ?? 0}<span className="text-sm font-medium text-ink-muted ml-0.5">건</span></p>
          </div>
          <div>
            <p className="text-sm text-ink-muted">실현 손익</p>
            <p className={`mt-0.5 text-xl font-bold tabular ${deltaClass(demo.realized_pnl_usd)}`}>{fmtUsd(demo.realized_pnl_usd ?? 0, { sign: true })}</p>
          </div>
          <div>
            <p className="text-sm text-ink-muted">수수료</p>
            <p className="mt-0.5 text-xl font-bold text-ink-secondary tabular">{fmtUsd(demo.fees_paid_usd ?? 0)}</p>
          </div>
        </div>

        <div>
          <p className="text-sm font-semibold text-ink-secondary mb-2">현재 포지션</p>
          {positions.length === 0 ? (
            <p className="text-sm text-ink-faint">보유 포지션 없음 (현금 대기)</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {positions.map(([pair, row]) => (
                <div key={pair} className="rounded-md border border-line px-3 py-2 text-sm">
                  <span className="font-semibold text-ink">{pair.replace("-USDT-SWAP", "")}</span>
                  <span className="text-ink-muted"> · {row.contracts} 계약 · 평단 </span>
                  <span className="tabular text-ink-secondary">{fmtPrice(row.avg_entry_price)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {demo.recent_trades && demo.recent_trades.length > 0 && (
          <div className="-mx-6 border-t border-line">
            <table className="w-full">
              <thead>
                <tr className="border-b border-line">
                  <Th className="pl-6">시각</Th>
                  <Th>종목</Th>
                  <Th>구분</Th>
                  <Th align="right">체결가</Th>
                  <Th align="right">결정가 대비</Th>
                  <Th align="right">금액</Th>
                  <Th align="right" className="pr-6">실현 손익</Th>
                </tr>
              </thead>
              <tbody>
                {demo.recent_trades.slice().reverse().slice(0, 8).map((t) => {
                  const slip = t.decision_price > 0 ? ((t.price / t.decision_price) - 1) * 100 : 0;
                  return (
                    <tr key={t.cl_ord_id} className="border-b border-line last:border-0">
                      <Td className="pl-6 text-sm text-ink-faint">{fmtDateTime(t.occurred_at)}</Td>
                      <Td className="font-semibold text-ink">{t.inst_id.replace("-USDT-SWAP", "")}</Td>
                      <Td><Badge tone={t.side === "buy" ? "red" : "blue"}>{t.side === "buy" ? "매수" : "매도"}</Badge></Td>
                      <Td align="right" className="text-ink-secondary">{fmtPrice(t.price)}</Td>
                      <Td align="right" className={`text-sm ${Math.abs(slip) > 0.5 ? "text-warn-strong" : "text-ink-faint"}`}>{slip >= 0 ? "+" : ""}{slip.toFixed(3)}%</Td>
                      <Td align="right" className="text-ink-secondary">{fmtUsd(t.notional_usd, { digits: 0 })}</Td>
                      <Td align="right" className={`pr-6 font-semibold ${deltaClass(t.realized_pnl_usd)}`}>
                        {t.realized_pnl_usd === null ? "-" : fmtUsd(t.realized_pnl_usd, { sign: true })}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function TradingTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [demo, setDemo] = useState<DemoTraderStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [h, r, d] = await Promise.allSettled([getHealth(), getRiskStatus(), getDemoTrader()]);
    if (h.status === "fulfilled") setHealth(h.value);
    if (r.status === "fulfilled") setRisk(r.value);
    if (d.status === "fulfilled") setDemo(d.value);
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function onEmergencyStop() {
    const reason = window.prompt("긴급 정지 사유를 입력하세요", "수동 긴급 정지");
    if (!reason) return;
    setBusy(true);
    try {
      await tripKillSwitch(reason);
      setRisk(await getRiskStatus());
    } catch (e) {
      window.alert(`킬스위치 발동 실패: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function onResume() {
    if (!window.confirm("킬스위치를 해제하고 신규 진입을 다시 허용할까요?")) return;
    setBusy(true);
    try {
      await resetKillSwitch();
      setRisk(await getRiskStatus());
    } catch (e) {
      window.alert(`킬스위치 해제 실패: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const mode = health?.okx_api.mode ?? null;
  const tripped = risk?.kill_switch.tripped ?? false;

  return (
    <div className="space-y-6">
      {mode === "live" && (
        <Notice tone="orange" title="실거래 모드가 켜져 있어요">
          실제 자금이 위험에 노출됩니다. 주문 전에 실행 중인 프로세스를 확인하세요.
        </Notice>
      )}

      <TraderCard demo={demo} tripped={tripped} />

      <Card
        title="킬스위치"
        sub="모든 신규 주문이 통과해야 하는 최종 관문입니다. 발동되면 청산 주문만 허용돼요."
        action={
          risk &&
          (tripped ? (
            <Button variant="primary" onClick={onResume} disabled={busy}>거래 재개</Button>
          ) : (
            <Button variant="danger" onClick={onEmergencyStop} disabled={busy}>긴급 정지</Button>
          ))
        }
      >
        {!risk ? (
          <Empty title="리스크 상태를 불러오지 못했어요" sub="봇 API 연결을 확인하세요" className="py-8" />
        ) : (
          <div className="space-y-5">
            <div className={`rounded-lg px-5 py-4 flex items-start gap-3 ${tripped ? "bg-danger-soft" : "bg-ok-soft"}`}>
              <div className="mt-1.5"><StatusDot ok={!tripped} pulse={tripped} /></div>
              <div className="min-w-0">
                <p className={`text-lg font-bold ${tripped ? "text-danger-strong" : "text-ok-strong"}`}>
                  {tripped ? "긴급 정지 중 · 신규 진입 차단" : "정상 · 거래 허용"}
                </p>
                <p className={`text-sm mt-0.5 ${tripped ? "text-danger-strong/80" : "text-ok-strong/80"}`}>
                  {tripped ? (risk.kill_switch.reason ?? "사유 없음") : "마지막 변경"}
                  {risk.kill_switch.changed_at && <> · {fmtDateTime(risk.kill_switch.changed_at)} · {risk.kill_switch.source ?? "-"}</>}
                </p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm font-semibold text-ink-secondary">사전 리스크 한도</p>
                <span className="text-xs text-ink-faint">.env 에서 설정 · 변경 시 봇 재시작</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {Object.entries(risk.limits).map(([key, value]) => {
                  const meta = LIMIT_LABELS[key] ?? { label: key, unit: "" };
                  return (
                    <div key={key} className="rounded-lg bg-surface-muted px-4 py-3">
                      <p className="text-sm text-ink-muted">{meta.label}</p>
                      <p className="mt-0.5 text-lg font-bold text-ink tabular">
                        {meta.unit === "USD" ? `$${fmtInt(Number(value))}` : Number(value).toLocaleString("en-US")}
                        {meta.unit && meta.unit !== "USD" && <span className="text-sm font-medium text-ink-muted ml-0.5">{meta.unit}</span>}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </Card>

      <Card title="연결 상태" sub="API · 데이터베이스 · 거래소">
        <div className="divide-y divide-line">
          <div className="flex items-center justify-between py-3">
            <span className="text-base text-ink-secondary">데이터베이스</span>
            <span className="inline-flex items-center gap-2 text-base font-semibold text-ink"><StatusDot ok={health?.db === "ok"} />{health?.db ?? "-"}</span>
          </div>
          <div className="flex items-center justify-between py-3">
            <span className="text-base text-ink-secondary">OKX API</span>
            <span className="inline-flex items-center gap-2 text-base font-semibold text-ink"><StatusDot ok={health?.okx_api.status === "ok"} />{health?.okx_api.status ?? "-"}</span>
          </div>
          <div className="flex items-center justify-between py-3">
            <span className="text-base text-ink-secondary">거래 모드</span>
            {mode ? <Badge tone={mode === "live" ? "orange" : "blue"}>{mode === "live" ? "실거래" : "데모"}</Badge> : <span className="text-ink-faint">-</span>}
          </div>
        </div>
      </Card>
    </div>
  );
}
