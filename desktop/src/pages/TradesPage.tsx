import { useEffect, useMemo, useState } from "react";
import { getTrades } from "@/lib/api";
import type { Trade, TradeSource } from "@/lib/types";
import { deltaClass, fmtUsd } from "@/lib/format";
import TradeTable from "@/components/TradeTable";
import { Button, Card, Notice, PageHeader, Segmented, Select, Skeleton } from "@/components/ui";

const PAGE_SIZE = 50;

export default function TradesPage() {
  const [source, setSource] = useState<TradeSource>("live");
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const [filterPair, setFilterPair] = useState("");
  const [filterStrategy, setFilterStrategy] = useState("");
  const [filterDirection, setFilterDirection] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setPage(1);
    getTrades({ source, limit: 500 })
      .then((rows) => alive && setAllTrades(rows))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [source]);

  const pairs = useMemo(() => [...new Set(allTrades.map((t) => t.pair))].sort(), [allTrades]);
  const strategies = useMemo(() => [...new Set(allTrades.map((t) => t.strategy_name))].sort(), [allTrades]);

  const filtered = useMemo(
    () =>
      allTrades.filter((t) => {
        if (filterPair && t.pair !== filterPair) return false;
        if (filterStrategy && t.strategy_name !== filterStrategy) return false;
        if (filterDirection && t.direction !== filterDirection) return false;
        return true;
      }),
    [allTrades, filterPair, filterStrategy, filterDirection],
  );

  const paginated = filtered.slice(0, page * PAGE_SIZE);
  const hasMore = paginated.length < filtered.length;
  const hasFilter = !!(filterPair || filterStrategy || filterDirection);

  const totalPnl = filtered.reduce((acc, t) => acc + (t.pnl ?? 0), 0);
  const closed = filtered.filter((t) => t.pnl !== null);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;

  function resetFilters() {
    setFilterPair("");
    setFilterStrategy("");
    setFilterDirection("");
    setPage(1);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="거래 내역"
        sub="체결된 모든 거래를 확인합니다"
        action={
          <Segmented
            value={source}
            onChange={(v) => {
              setSource(v);
              resetFilters();
            }}
            options={[
              { value: "live", label: "실거래" },
              { value: "paper", label: "페이퍼" },
            ]}
          />
        }
      />

      {/* 요약 */}
      <section className="grid grid-cols-3 gap-4">
        <div className="bg-surface border border-line rounded-xl shadow-card p-5">
          <p className="text-sm text-ink-muted">거래 수</p>
          <p className="mt-1 text-2xl font-bold text-ink tabular">{filtered.length}<span className="text-base font-medium text-ink-muted ml-0.5">건</span></p>
        </div>
        <div className="bg-surface border border-line rounded-xl shadow-card p-5">
          <p className="text-sm text-ink-muted">합계 손익</p>
          <p className={`mt-1 text-2xl font-bold tabular ${deltaClass(totalPnl)}`}>{fmtUsd(totalPnl, { sign: true })}</p>
        </div>
        <div className="bg-surface border border-line rounded-xl shadow-card p-5">
          <p className="text-sm text-ink-muted">승률</p>
          <p className="mt-1 text-2xl font-bold text-ink tabular">
            {closed.length ? `${((wins / closed.length) * 100).toFixed(1)}%` : "-"}
            {closed.length > 0 && <span className="text-base font-medium text-ink-muted ml-1.5">{wins}/{closed.length}</span>}
          </p>
        </div>
      </section>

      <Card padded={false}>
        {/* 필터 바 */}
        <div className="px-6 h-16 flex items-center gap-2 border-b border-line">
          <Select value={filterPair} onChange={(v) => { setFilterPair(v); setPage(1); }}>
            <option value="">전체 종목</option>
            {pairs.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </Select>
          <Select value={filterStrategy} onChange={(v) => { setFilterStrategy(v); setPage(1); }} className="max-w-[260px]">
            <option value="">전체 전략</option>
            {strategies.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
          <Select value={filterDirection} onChange={(v) => { setFilterDirection(v); setPage(1); }}>
            <option value="">전체 방향</option>
            <option value="long">롱</option>
            <option value="short">숏</option>
          </Select>
          {hasFilter && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              초기화
            </Button>
          )}
          <span className="ml-auto text-sm text-ink-faint tabular">
            {paginated.length} / {filtered.length}건 표시
          </span>
        </div>

        {loading ? (
          <div className="p-6 space-y-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="p-6">
            <Notice tone="red" title="거래 내역을 불러오지 못했습니다">{error}</Notice>
          </div>
        ) : (
          <TradeTable trades={paginated} />
        )}

        {!loading && hasMore && (
          <div className="px-6 py-4 border-t border-line flex justify-center">
            <Button variant="secondary" onClick={() => setPage((p) => p + 1)}>
              더 보기 ({filtered.length - paginated.length}건)
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
