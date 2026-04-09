"use client";

import { useEffect, useRef, useState } from "react";
import { getMarkets } from "@/lib/api";
import type { MarketTicker } from "@/lib/types";

// ── Formatting ───────────────────────────────────────────────────────────────

function formatPrice(price: number): string {
  if (price >= 1000) return "$" + price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (price >= 1) return "$" + price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  if (price >= 0.01) return "$" + price.toFixed(4);
  return "$" + price.toFixed(8);
}

function formatVolume(v: number): string {
  if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  return "$" + v.toFixed(0);
}

// ── Sort types ───────────────────────────────────────────────────────────────

type SortKey = "volume_24h" | "price" | "change_pct_24h" | "name" | "high_24h" | "low_24h";
type SortDir = "asc" | "desc";

// ── Sector badge colors ──────────────────────────────────────────────────────

const SECTOR_COLORS: Record<string, string> = {
  "Layer 1": "bg-blue-500/20 text-blue-400",
  "Layer 2": "bg-purple-500/20 text-purple-400",
  "DeFi": "bg-emerald-500/20 text-emerald-400",
  "Meme": "bg-yellow-500/20 text-yellow-400",
  "AI": "bg-cyan-500/20 text-cyan-400",
  "Gaming": "bg-pink-500/20 text-pink-400",
  "Oracle": "bg-orange-500/20 text-orange-400",
  "Payments": "bg-lime-500/20 text-lime-400",
  "Storage": "bg-indigo-500/20 text-indigo-400",
  "Infrastructure": "bg-slate-400/20 text-slate-300",
  "NFT": "bg-rose-500/20 text-rose-400",
  "BRC-20": "bg-amber-500/20 text-amber-400",
  "RWA": "bg-teal-500/20 text-teal-400",
  "IoT": "bg-violet-500/20 text-violet-400",
  "Other": "bg-slate-600/20 text-slate-400",
};

// ── Components ───────────────────────────────────────────────────────────────

function CoinIcon({ iconUrl, symbol }: { iconUrl: string; symbol: string }) {
  const [failed, setFailed] = useState(false);
  const letter = symbol.charAt(0).toUpperCase();
  const colors = ["bg-blue-500", "bg-purple-500", "bg-emerald-500", "bg-amber-500", "bg-rose-500", "bg-cyan-500", "bg-indigo-500", "bg-teal-500"];
  const bg = colors[symbol.charCodeAt(0) % colors.length];

  if (failed || !iconUrl) {
    return (
      <div className={`w-8 h-8 rounded-full ${bg} flex items-center justify-center shrink-0`}>
        <span className="text-white text-xs font-bold">{letter}</span>
      </div>
    );
  }
  return (
    <img src={iconUrl} alt={symbol} width={32} height={32}
      className="w-8 h-8 rounded-full shrink-0 object-cover bg-slate-700"
      onError={() => setFailed(true)} />
  );
}

function SortHeader({ label, sortKey, currentSort, currentDir, onSort }: {
  label: string; sortKey: SortKey; currentSort: SortKey; currentDir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  const active = currentSort === sortKey;
  return (
    <th
      onClick={() => onSort(sortKey)}
      className="py-3 px-3 text-right text-xs font-medium uppercase tracking-wider cursor-pointer select-none hover:text-slate-300 transition-colors"
    >
      <span className={active ? "text-blue-400" : "text-slate-500"}>
        {label}
        {active && (
          <span className="ml-1">{currentDir === "desc" ? "▼" : "▲"}</span>
        )}
      </span>
    </th>
  );
}

function SkeletonRow({ rank }: { rank: number }) {
  return (
    <tr className="border-b border-slate-800/60 animate-pulse">
      <td className="py-3.5 pl-4 pr-2 text-slate-600 text-sm w-10">{rank}</td>
      <td className="py-3.5 px-3"><div className="flex items-center gap-3"><div className="w-8 h-8 rounded-full bg-slate-700/60 shrink-0" /><div className="space-y-1.5"><div className="h-3.5 w-20 rounded bg-slate-700/60" /><div className="h-2.5 w-12 rounded bg-slate-700/40" /></div></div></td>
      <td className="py-3.5 px-3"><div className="h-5 w-14 rounded bg-slate-700/40 ml-auto" /></td>
      <td className="py-3.5 px-3"><div className="h-3.5 w-24 rounded bg-slate-700/60 ml-auto" /></td>
      <td className="py-3.5 px-3"><div className="h-3.5 w-16 rounded bg-slate-700/60 ml-auto" /></td>
      <td className="py-3.5 px-3"><div className="h-3.5 w-20 rounded bg-slate-700/60 ml-auto" /></td>
      <td className="py-3.5 px-3"><div className="h-3.5 w-20 rounded bg-slate-700/60 ml-auto" /></td>
      <td className="py-3.5 px-3 pr-4"><div className="h-3.5 w-20 rounded bg-slate-700/60 ml-auto" /></td>
    </tr>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function MarketsPage() {
  const [tickers, setTickers] = useState<MarketTicker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("volume_24h");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedSector, setSelectedSector] = useState<string>("All");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchData() {
    try {
      const data = await getMarkets();
      setTickers(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "마켓 데이터 로드 실패");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    intervalRef.current = setInterval(fetchData, 10_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === "desc" ? "asc" : "desc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  // Derive sectors from data
  const sectors = ["All", ...Array.from(new Set(tickers.map(t => t.sector))).sort()];

  // Filter
  const filtered = tickers.filter(t => {
    const q = search.toLowerCase();
    const matchSearch = !q || t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q);
    const matchSector = selectedSector === "All" || t.sector === selectedSector;
    return matchSearch && matchSector;
  });

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case "name": cmp = a.name.localeCompare(b.name); break;
      case "price": cmp = a.price - b.price; break;
      case "change_pct_24h": cmp = a.change_pct_24h - b.change_pct_24h; break;
      case "volume_24h": cmp = a.volume_24h - b.volume_24h; break;
      case "high_24h": cmp = a.high_24h - b.high_24h; break;
      case "low_24h": cmp = a.low_24h - b.low_24h; break;
    }
    return sortDir === "desc" ? -cmp : cmp;
  });

  // Stats
  const gainers = tickers.filter(t => t.change_pct_24h > 0).length;
  const losers = tickers.filter(t => t.change_pct_24h < 0).length;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-white tracking-tight">마켓</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {lastUpdated ? `갱신됨 ${lastUpdated.toLocaleTimeString()}` : "로딩 중…"}
            {!loading && <span className="ml-3 text-emerald-400">{gainers} ▲</span>}
            {!loading && <span className="ml-2 text-rose-400">{losers} ▼</span>}
          </p>
        </div>

        {/* Search */}
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input type="text" placeholder="코인 검색…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-56 bg-[#161b27] border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-slate-500 transition-colors" />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          )}
        </div>
      </div>

      {/* Sector filter pills */}
      <div className="flex gap-2 flex-wrap">
        {sectors.map(sector => (
          <button key={sector} onClick={() => setSelectedSector(sector)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              selectedSector === sector
                ? "bg-blue-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            }`}>
            {sector}
            {sector !== "All" && (
              <span className="ml-1.5 text-slate-500">
                {tickers.filter(t => t.sector === sector).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-rose-500/10 border border-rose-500/30 rounded-lg px-4 py-3 text-sm text-rose-400">
          <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
          {error}
        </div>
      )}

      {/* Table */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-[#161b27]">
                <th className="py-3 pl-4 pr-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-10">#</th>
                <th onClick={() => handleSort("name")}
                  className="py-3 px-3 text-left text-xs font-medium uppercase tracking-wider cursor-pointer select-none hover:text-slate-300 transition-colors">
                  <span className={sortKey === "name" ? "text-blue-400" : "text-slate-500"}>
                    Coin{sortKey === "name" && <span className="ml-1">{sortDir === "desc" ? "▼" : "▲"}</span>}
                  </span>
                </th>
                <th className="py-3 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-20">섹터</th>
                <SortHeader label="가격" sortKey="price" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
                <SortHeader label="24시간 %" sortKey="change_pct_24h" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
                <SortHeader label="거래량" sortKey="volume_24h" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
                <SortHeader label="고가" sortKey="high_24h" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
                <SortHeader label="저가" sortKey="low_24h" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading ? (
                Array.from({ length: 15 }, (_, i) => <SkeletonRow key={i} rank={i + 1} />)
              ) : sorted.length === 0 ? (
                <tr><td colSpan={8} className="py-16 text-center text-slate-500">
                  {search || selectedSector !== "All" ? "필터에 맞는 코인이 없습니다" : "마켓 데이터 없음"}
                </td></tr>
              ) : (
                sorted.map((t, idx) => (
                  <tr key={t.pair} className="hover:bg-slate-800/30 transition-colors duration-100">
                    <td className="py-3.5 pl-4 pr-2 text-slate-500 text-sm tabular-nums w-10">{idx + 1}</td>
                    <td className="py-3.5 px-3">
                      <div className="flex items-center gap-3">
                        <CoinIcon iconUrl={t.icon_url} symbol={t.symbol} />
                        <div className="min-w-0">
                          <div className="font-medium text-slate-100 truncate">{t.name}</div>
                          <div className="text-xs text-slate-500 mt-0.5">{t.symbol}</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3.5 px-3">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-medium ${SECTOR_COLORS[t.sector] || SECTOR_COLORS["Other"]}`}>
                        {t.sector}
                      </span>
                    </td>
                    <td className="py-3.5 px-3 text-right font-medium text-slate-100 tabular-nums">{formatPrice(t.price)}</td>
                    <td className="py-3.5 px-3 text-right">
                      <span className={`inline-flex items-center gap-0.5 font-medium tabular-nums ${t.change_pct_24h >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {t.change_pct_24h >= 0 ? (
                          <svg className="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="currentColor"><path d="M7 14l5-5 5 5H7z" /></svg>
                        ) : (
                          <svg className="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5H7z" /></svg>
                        )}
                        {(t.change_pct_24h >= 0 ? "+" : "") + t.change_pct_24h.toFixed(2) + "%"}
                      </span>
                    </td>
                    <td className="py-3.5 px-3 text-right text-slate-300 tabular-nums">{formatVolume(t.volume_24h)}</td>
                    <td className="py-3.5 px-3 text-right text-emerald-400/80 tabular-nums">{formatPrice(t.high_24h)}</td>
                    <td className="py-3.5 px-3 pr-4 text-right text-rose-400/80 tabular-nums">{formatPrice(t.low_24h)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {!loading && sorted.length > 0 && (
          <div className="px-4 py-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-600">
            <span>{sorted.length}개 코인{selectedSector !== "All" ? ` (${selectedSector})` : ""}</span>
            <span>10초마다 자동 갱신</span>
          </div>
        )}
      </div>
    </div>
  );
}
