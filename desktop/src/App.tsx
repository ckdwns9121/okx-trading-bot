import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import OverviewPage from "@/pages/OverviewPage";
import MarketsPage from "@/pages/MarketsPage";
import TradesPage from "@/pages/TradesPage";
import ConfigPage from "@/pages/ConfigPage";

const NAV_ITEMS = [
  { label: "대시보드", href: "/" },
  { label: "마켓", href: "/markets" },
  { label: "거래 내역", href: "/trades" },
  { label: "설정", href: "/config" },
] as const;

export default function App() {
  return (
    <div className="flex min-h-screen bg-[#0f1117] text-slate-100">
      <aside className="w-56 shrink-0 bg-[#161b27] border-r border-slate-800 flex flex-col py-6">
        <div className="px-6 mb-8">
          <span className="text-lg font-bold tracking-tight text-white">OKX Bot</span>
          <p className="text-xs text-slate-500 mt-0.5">Desktop Dashboard</p>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {NAV_ITEMS.map(({ label, href }) => (
            <NavLink
              key={href}
              to={href}
              end={href === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150 ${
                  isActive
                    ? "text-white bg-slate-700/70"
                    : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                }`
              }
            >
              <NavIcon label={label} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-6 mt-4">
          <p className="text-xs text-slate-600">desktop v0.1.0</p>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/markets" element={<MarketsPage />} />
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function NavIcon({ label }: { label: string }) {
  const cls = "w-4 h-4 shrink-0";
  switch (label) {
    case "대시보드":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case "마켓":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
          <polyline points="16 7 22 7 22 13" />
        </svg>
      );
    case "거래 내역":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <line x1="12" y1="1" x2="12" y2="23" />
          <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      );
    case "설정":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
    default:
      return null;
  }
}
