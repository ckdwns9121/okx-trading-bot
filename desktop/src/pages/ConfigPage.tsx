import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/ui";
import TradingTab from "./settings/TradingTab";
import BacktestTab from "./settings/BacktestTab";
import ThemeTab from "./settings/ThemeTab";
import LogsTab from "./settings/LogsTab";

type TabKey = "trading" | "backtest" | "theme" | "logs";

const TABS: { key: TabKey; label: string; desc: string }[] = [
  { key: "trading", label: "거래 설정", desc: "트레이더 상태 · 킬스위치 · 리스크 한도" },
  { key: "backtest", label: "백테스트", desc: "전략을 과거 데이터로 검증" },
  { key: "theme", label: "테마", desc: "라이트 · 다크 · 시스템" },
  { key: "logs", label: "로그", desc: "신호 · 주문 · 체결 이벤트" },
];

/** 토스식 밑줄 탭 — 활성 탭만 진하게, 아래 2px 라인 */
function TabBar({ value, onChange }: { value: TabKey; onChange: (k: TabKey) => void }) {
  return (
    <div className="border-b border-line -mx-1">
      <div className="flex gap-1 px-1">
        {TABS.map((t) => {
          const active = t.key === value;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => onChange(t.key)}
              className={`relative h-11 px-3 text-base font-semibold transition-colors ${
                active ? "text-ink" : "text-ink-faint hover:text-ink-secondary"
              }`}
            >
              {t.label}
              {active && <span className="absolute left-3 right-3 -bottom-px h-0.5 bg-ink rounded-full" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function ConfigPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === raw) ? (raw as TabKey) : "trading";
  const current = TABS.find((t) => t.key === tab)!;

  function select(next: TabKey) {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    setParams(p, { replace: true });
  }

  return (
    <div className="space-y-6">
      <PageHeader title="설정" sub={current.desc} />
      <TabBar value={tab} onChange={select} />
      {tab === "trading" && <TradingTab />}
      {tab === "backtest" && <BacktestTab />}
      {tab === "theme" && <ThemeTab />}
      {tab === "logs" && <LogsTab />}
    </div>
  );
}
