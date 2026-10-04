import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import OverviewPage from "@/pages/OverviewPage";
import MarketsPage from "@/pages/MarketsPage";
import TradesPage from "@/pages/TradesPage";
import ConfigPage from "@/pages/ConfigPage";
import { getHealth, getRiskStatus } from "@/lib/api";
import type { HealthStatus, RiskStatus } from "@/lib/types";
import { Badge, StatusDot } from "@/components/ui";
import { Logo } from "@/components/Logo";

const NAV_ITEMS = [
  { label: "홈", href: "/" },
  { label: "마켓", href: "/markets" },
  { label: "거래 내역", href: "/trades" },
  { label: "설정", href: "/config" },
] as const;

/** 상단 바 오른쪽: 거래 모드와 킬스위치 상태를 항상 보이게 */
function StatusCluster({ health, risk }: { health: HealthStatus | null; risk: RiskStatus | null }) {
  const navigate = useNavigate();
  const mode = health?.okx_api.mode;
  const tripped = risk?.kill_switch.tripped ?? false;
  return (
    <div className="flex items-center gap-2">
      {mode && (
        <Badge tone={mode === "live" ? "orange" : "blue"}>
          {mode === "live" ? "실거래" : "데모"}
        </Badge>
      )}
      <button
        type="button"
        onClick={() => navigate("/config")}
        className={`h-8 inline-flex items-center gap-2 pl-3 pr-3.5 rounded-full text-sm font-semibold transition-colors ${
          risk === null
            ? "bg-surface-muted text-ink-faint"
            : tripped
              ? "bg-danger-soft text-danger-strong hover:bg-surface-hover"
              : "bg-surface-muted text-ink-secondary hover:bg-surface-hover"
        }`}
      >
        <StatusDot ok={!tripped} pulse={tripped} />
        {risk === null ? "연결 중" : tripped ? "긴급 정지 중" : "거래 허용"}
      </button>
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);

  useEffect(() => {
    let alive = true;
    async function poll() {
      const [h, r] = await Promise.allSettled([getHealth(), getRiskStatus()]);
      if (!alive) return;
      if (h.status === "fulfilled") setHealth(h.value);
      if (r.status === "fulfilled") setRisk(r.value);
    }
    void poll();
    const timer = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // "/" 키로 마켓 검색 이동 (토스증권의 / 단축키)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA");
      if (e.key === "/" && !typing) {
        e.preventDefault();
        navigate("/markets?focus=search");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="min-h-screen bg-bg text-ink flex flex-col">
      {/*
        macOS 타이틀바를 숨기고(tauri.conf.json: titleBarStyle Overlay) 이 헤더가 그 역할을 한다.
        data-tauri-drag-region 으로 창을 끌 수 있고, 왼쪽 92px는 신호등 버튼 자리로 비워 둔다.
      */}
      <header
        data-tauri-drag-region
        className="sticky top-0 z-30 bg-bg/90 backdrop-blur border-b border-line select-none"
      >
        <div data-tauri-drag-region className="h-[52px] pl-[88px] pr-5 flex items-center gap-6">
          <Logo />
          <nav className="flex items-center gap-0.5">
            {NAV_ITEMS.map(({ label, href }) => (
              <NavLink
                key={href}
                to={href}
                end={href === "/"}
                className={({ isActive }) =>
                  `inline-flex items-center h-8 px-2.5 rounded-sm text-sm font-semibold leading-none transition-colors ${
                    isActive ? "text-ink" : "text-ink-muted hover:text-ink hover:bg-surface-muted"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate("/markets?focus=search")}
              className="hidden md:inline-flex h-8 w-56 items-center gap-2 px-3 rounded-sm bg-surface-muted text-ink-faint text-sm hover:bg-surface-hover transition-colors"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
                <circle cx="11" cy="11" r="7" />
                <line x1="20" y1="20" x2="16.5" y2="16.5" />
              </svg>
              <kbd className="h-5 px-1.5 rounded-sm bg-surface text-xs font-semibold text-ink-muted border border-line">/</kbd>
              <span>를 눌러 검색하세요</span>
            </button>
            <StatusCluster health={health} risk={risk} />
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-[1200px] mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/markets" element={<MarketsPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>

      <footer className="border-t border-line">
        <div className="max-w-[1200px] mx-auto px-6 h-12 flex items-center justify-between text-xs text-ink-faint">
          <span>투자 손실 위험이 있습니다. 학습·실험 목적의 데모 트레이딩 도구입니다.</span>
          <span>desktop v0.2.0</span>
        </div>
      </footer>
    </div>
  );
}
