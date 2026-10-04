import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getMarkets } from "@/lib/api";
import type { MarketTicker } from "@/lib/types";
import { deltaClass, fmtCompactUsd, fmtPct, fmtPrice, fmtTime } from "@/lib/format";
import {
  Badge,
  Chip,
  CoinAvatar,
  Delta,
  Empty,
  Notice,
  PageHeader,
  SearchInput,
  Skeleton,
  StatTile,
  Td,
  Th,
} from "@/components/ui";

type SortKey = "volume_24h" | "price" | "change_pct_24h" | "name" | "high_24h" | "low_24h";
type SortDir = "asc" | "desc";

const HERO_SYMBOLS = ["BTC", "ETH", "SOL", "XRP"];
const REFRESH_MS = 10_000;

export default function MarketsPage() {
  const [params] = useSearchParams();
  const searchRef = useRef<HTMLDivElement>(null);

  const [tickers, setTickers] = useState<MarketTicker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("All");
  const [sortKey, setSortKey] = useState<SortKey>("volume_24h");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // 직전 가격을 기억해 두었다가 바뀐 칸만 잠깐 깜빡인다
  const prevPrices = useRef<Record<string, number>>({});
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await getMarkets();
        if (!alive) return;
        const next: Record<string, "up" | "down"> = {};
        for (const t of data) {
          const prev = prevPrices.current[t.pair];
          if (prev !== undefined && prev !== t.price) next[t.pair] = t.price > prev ? "up" : "down";
          prevPrices.current[t.pair] = t.price;
        }
        setFlash(next);
        setTickers(data);
        setLastUpdated(new Date());
        setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "마켓 데이터를 불러오지 못했습니다");
      } finally {
        if (alive) setLoading(false);
      }
    }
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // 상단 바의 "/" 단축키로 들어오면 검색창에 포커스
  useEffect(() => {
    if (params.get("focus") === "search") {
      searchRef.current?.querySelector("input")?.focus();
    }
  }, [params]);

  const sectors = useMemo(
    () => ["All", ...Array.from(new Set(tickers.map((t) => t.sector))).sort()],
    [tickers],
  );
  const sectorCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of tickers) counts[t.sector] = (counts[t.sector] ?? 0) + 1;
    return counts;
  }, [tickers]);

  const hero = useMemo(
    () => HERO_SYMBOLS.map((s) => tickers.find((t) => t.symbol === s)).filter((t): t is MarketTicker => !!t),
    [tickers],
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = tickers.filter((t) => {
      const matchQ = !q || t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q);
      const matchS = sector === "All" || t.sector === sector;
      return matchQ && matchS;
    });
    return [...filtered].sort((a, b) => {
      const cmp = sortKey === "name" ? a.name.localeCompare(b.name) : a[sortKey] - b[sortKey];
      return sortDir === "desc" ? -cmp : cmp;
    });
  }, [tickers, search, sector, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  const gainers = tickers.filter((t) => t.change_pct_24h > 0).length;
  const losers = tickers.filter((t) => t.change_pct_24h < 0).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="마켓"
        sub={
          loading ? (
            "불러오는 중…"
          ) : (
            <span className="inline-flex items-center gap-3">
              <span>OKX 무기한 선물 · 거래대금 상위 100</span>
              <span className="text-up font-semibold tabular">{gainers} ▲</span>
              <span className="text-down font-semibold tabular">{losers} ▼</span>
              {lastUpdated && <span className="text-ink-faint">{fmtTime(lastUpdated.toISOString())} 갱신</span>}
            </span>
          )
        }
        action={
          <div ref={searchRef}>
            <SearchInput value={search} onChange={setSearch} placeholder="코인 검색" className="w-72" />
          </div>
        }
      />

      {error && (
        <Notice tone="red" title="시세를 불러오지 못했습니다">
          {error}
        </Notice>
      )}

      {/* 주요 코인 — 토스의 지수 카드 */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {loading
          ? Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="bg-surface border border-line rounded-xl shadow-card p-5 space-y-3">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-8 w-32" />
                <Skeleton className="h-4 w-24" />
              </div>
            ))
          : hero.map((t) => (
              <StatTile
                key={t.pair}
                label={
                  <span className="inline-flex items-center gap-2">
                    <CoinAvatar iconUrl={t.icon_url} symbol={t.symbol} size={20} />
                    {t.name}
                  </span>
                }
                value={fmtPrice(t.price)}
                delta={<Delta abs={t.change_24h} pct={t.change_pct_24h} digits={t.price >= 1 ? 2 : 6} />}
              />
            ))}
      </section>

      {/* 필터 */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 -mb-1">
        {sectors.map((s) => (
          <Chip key={s} active={sector === s} onClick={() => setSector(s)} count={s === "All" ? undefined : sectorCounts[s]}>
            {s === "All" ? "전체" : s}
          </Chip>
        ))}
      </div>

      {/* 표 */}
      <section className="bg-surface border border-line rounded-xl shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse">
            <thead>
              <tr className="border-b border-line">
                <Th className="w-14 pl-6">#</Th>
                <Th onClick={() => toggleSort("name")} active={sortKey === "name"} dir={sortDir}>
                  종목
                </Th>
                <Th align="right" onClick={() => toggleSort("price")} active={sortKey === "price"} dir={sortDir}>
                  현재가
                </Th>
                <Th align="right" onClick={() => toggleSort("change_pct_24h")} active={sortKey === "change_pct_24h"} dir={sortDir}>
                  등락률
                </Th>
                <Th align="right" onClick={() => toggleSort("volume_24h")} active={sortKey === "volume_24h"} dir={sortDir}>
                  거래대금
                </Th>
                <Th align="right" onClick={() => toggleSort("high_24h")} active={sortKey === "high_24h"} dir={sortDir}>
                  고가
                </Th>
                <Th align="right" onClick={() => toggleSort("low_24h")} active={sortKey === "low_24h"} dir={sortDir}>
                  저가
                </Th>
                <Th className="pr-6">섹터</Th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 12 }, (_, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <Td className="pl-6 text-ink-faint">{i + 1}</Td>
                    <Td>
                      <div className="flex items-center gap-3">
                        <Skeleton className="w-9 h-9 rounded-full" />
                        <div className="space-y-1.5">
                          <Skeleton className="h-4 w-24" />
                          <Skeleton className="h-3 w-12" />
                        </div>
                      </div>
                    </Td>
                    <Td align="right"><Skeleton className="h-4 w-20 ml-auto" /></Td>
                    <Td align="right"><Skeleton className="h-4 w-16 ml-auto" /></Td>
                    <Td align="right"><Skeleton className="h-4 w-16 ml-auto" /></Td>
                    <Td align="right"><Skeleton className="h-4 w-20 ml-auto" /></Td>
                    <Td align="right"><Skeleton className="h-4 w-20 ml-auto" /></Td>
                    <Td className="pr-6"><Skeleton className="h-6 w-14" /></Td>
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <Empty
                      title={search || sector !== "All" ? "조건에 맞는 코인이 없어요" : "마켓 데이터가 없어요"}
                      sub={search ? `"${search}" 검색 결과가 없습니다` : undefined}
                    />
                  </td>
                </tr>
              ) : (
                rows.map((t, idx) => {
                  const f = flash[t.pair];
                  return (
                    <tr key={t.pair} className="border-b border-line last:border-0 hover:bg-bg-subtle transition-colors">
                      <Td className="pl-6 text-ink-faint">{idx + 1}</Td>
                      <Td>
                        <div className="flex items-center gap-3 min-w-0">
                          <CoinAvatar iconUrl={t.icon_url} symbol={t.symbol} />
                          <div className="min-w-0">
                            <div className="font-semibold text-ink truncate">{t.name}</div>
                            <div className="text-xs text-ink-faint">{t.symbol}</div>
                          </div>
                        </div>
                      </Td>
                      <Td align="right" className="font-semibold text-ink">
                        <span
                          key={`${t.pair}-${t.price}`}
                          className={`inline-block rounded-sm px-1 -mx-1 ${f ? `flash-${f}` : ""}`}
                        >
                          {fmtPrice(t.price)}
                        </span>
                      </Td>
                      <Td align="right" className={`font-semibold ${deltaClass(t.change_pct_24h)}`}>
                        {fmtPct(t.change_pct_24h)}
                      </Td>
                      <Td align="right" className="text-ink-secondary">{fmtCompactUsd(t.volume_24h)}</Td>
                      <Td align="right" className="text-ink-secondary">{fmtPrice(t.high_24h)}</Td>
                      <Td align="right" className="text-ink-secondary">{fmtPrice(t.low_24h)}</Td>
                      <Td className="pr-6">
                        <Badge tone="grey">{t.sector}</Badge>
                      </Td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {!loading && rows.length > 0 && (
          <div className="px-6 h-12 border-t border-line flex items-center justify-between text-xs text-ink-faint">
            <span>
              {rows.length}개 종목{sector !== "All" ? ` · ${sector}` : ""}
            </span>
            <span>10초마다 자동 갱신 · 등락률은 24시간 기준</span>
          </div>
        )}
      </section>
    </div>
  );
}
