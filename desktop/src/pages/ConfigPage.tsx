import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import TradingTab from "./settings/TradingTab";
import BacktestTab from "./settings/BacktestTab";
import ThemeTab from "./settings/ThemeTab";
import LogsTab from "./settings/LogsTab";

type TabKey = "trading" | "backtest" | "theme" | "logs";

const TABS: { key: TabKey; label: string; desc: string; icon: ReactNode }[] = [
  {
    key: "trading",
    label: "거래 설정",
    desc: "트레이더 상태 · 킬스위치 · 리스크 한도",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
  },
  {
    key: "backtest",
    label: "백테스트",
    desc: "전략을 과거 데이터로 검증",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 17l6-6 4 4 8-8" />
        <path d="M14 7h7v7" />
      </svg>
    ),
  },
  {
    key: "theme",
    label: "테마",
    desc: "라이트 · 다크 · 시스템",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    key: "logs",
    label: "로그",
    desc: "신호 · 주문 · 체결 이벤트",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 4h14v16H5z" />
        <path d="M8 9h8M8 13h8M8 17h5" />
      </svg>
    ),
  },
];

/** 왼쪽 세로 메뉴 — macOS 시스템 설정처럼 아이콘 + 라벨, 활성 항목은 채운 배경 */
function SideNav({ value, onChange }: { value: TabKey; onChange: (k: TabKey) => void }) {
  return (
    <nav className="w-56 shrink-0 sticky top-[68px] self-start">
      <ul className="space-y-0.5">
        {TABS.map((t) => {
          const active = t.key === value;
          return (
            <li key={t.key}>
              <button
                type="button"
                onClick={() => onChange(t.key)}
                aria-current={active ? "page" : undefined}
                className={`w-full flex items-center gap-3 h-10 px-3 rounded-md text-left transition-colors ${
                  active
                    ? "bg-ink text-bg"
                    : "text-ink-secondary hover:bg-surface-muted hover:text-ink"
                }`}
              >
                <span className={`w-4.5 h-4.5 shrink-0 [&>svg]:w-[18px] [&>svg]:h-[18px] ${active ? "text-bg" : "text-ink-faint"}`}>
                  {t.icon}
                </span>
                <span className="text-base font-semibold">{t.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
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
    <div className="flex items-start gap-8">
      <SideNav value={tab} onChange={select} />

      <section className="flex-1 min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-ink tracking-tight">{current.label}</h1>
          <p className="text-sm text-ink-muted mt-1">{current.desc}</p>
        </div>
        {tab === "trading" && <TradingTab />}
        {tab === "backtest" && <BacktestTab />}
        {tab === "theme" && <ThemeTab />}
        {tab === "logs" && <LogsTab />}
      </section>
    </div>
  );
}
