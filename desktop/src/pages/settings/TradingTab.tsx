import { useCallback, useEffect, useState } from "react";
import { getHealth, getRiskStatus, resetKillSwitch, tripKillSwitch } from "@/lib/api";
import type { HealthStatus, RiskStatus } from "@/lib/types";
import { fmtDateTime, fmtInt } from "@/lib/format";
import { Badge, Button, Card, Empty, Notice, StatusDot } from "@/components/ui";

const LIMIT_LABELS: Record<string, { label: string; unit: string }> = {
  max_order_notional_usd: { label: "주문당 최대 금액", unit: "USD" },
  max_instrument_notional_usd: { label: "종목당 최대 포지션", unit: "USD" },
  max_total_exposure_usd: { label: "총 노출 한도", unit: "USD" },
  max_price_deviation_pct: { label: "가격 괴리 한도", unit: "%" },
  max_daily_loss_usd: { label: "일일 손실 한도", unit: "USD" },
  max_orders_per_minute: { label: "분당 최대 주문", unit: "건" },
};

const REFRESH_MS = 5_000;

export default function TradingTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [h, r] = await Promise.allSettled([getHealth(), getRiskStatus()]);
    if (h.status === "fulfilled") setHealth(h.value);
    if (r.status === "fulfilled") setRisk(r.value);
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

      <Notice tone="blue" title="지금은 돌아가는 전략이 없어요">
        기존 전략은 2026-10-04에 모두 제거했습니다. 새 전략은 백테스트 → 페이퍼 → 데모 검증을 통과한 뒤에만 여기에 연결됩니다.
      </Notice>

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
