"use client";

import { useEffect, useState } from "react";
import { getTrades } from "@/lib/api";
import type { Trade } from "@/lib/types";
import TradeTable from "@/components/TradeTable";

type Source = "live" | "paper";

const PAGE_SIZE = 50;

export default function TradesPage() {
  const [source, setSource] = useState<Source>("live");
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // Filters
  const [filterPair, setFilterPair] = useState("");
  const [filterStrategy, setFilterStrategy] = useState("");
  const [filterDirection, setFilterDirection] = useState<"" | "long" | "short">("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    setPage(1);
    getTrades({ source, limit: 500 })
      .then(setAllTrades)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [source]);

  // Derived filter options
  const pairs = [...new Set(allTrades.map((t) => t.pair))].sort();
  const strategies = [...new Set(allTrades.map((t) => t.strategy_name))].sort();

  const filtered = allTrades.filter((t) => {
    if (filterPair && t.pair !== filterPair) return false;
    if (filterStrategy && t.strategy_name !== filterStrategy) return false;
    if (filterDirection && t.direction !== filterDirection) return false;
    return true;
  });

  const paginated = filtered.slice(0, page * PAGE_SIZE);
  const hasMore = paginated.length < filtered.length;

  const inputCls =
    "bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 transition-colors";

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">거래 내역</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          체결된 모든 거래를 확인합니다
        </p>
      </div>

      {/* Tab toggle */}
      <div className="flex gap-1 bg-[#161b27] border border-slate-800 rounded-lg p-1 w-fit">
        {(["live", "paper"] as Source[]).map((s) => (
          <button
            key={s}
            onClick={() => {
              setSource(s);
              setFilterPair("");
              setFilterStrategy("");
              setFilterDirection("");
            }}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              source === s
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white"
            }`}
          >
            {s === "live" ? "실시간 거래" : "페이퍼 거래"}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select
          value={filterPair}
          onChange={(e) => { setFilterPair(e.target.value); setPage(1); }}
          className={inputCls}
        >
          <option value="">전체 거래쌍</option>
          {pairs.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <select
          value={filterStrategy}
          onChange={(e) => { setFilterStrategy(e.target.value); setPage(1); }}
          className={inputCls}
        >
          <option value="">전체 전략</option>
          {strategies.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={filterDirection}
          onChange={(e) => {
            setFilterDirection(e.target.value as "" | "long" | "short");
            setPage(1);
          }}
          className={inputCls}
        >
          <option value="">전체 방향</option>
          <option value="long">롱</option>
          <option value="short">숏</option>
        </select>

        {(filterPair || filterStrategy || filterDirection) && (
          <button
            onClick={() => {
              setFilterPair("");
              setFilterStrategy("");
              setFilterDirection("");
              setPage(1);
            }}
            className="text-xs text-slate-500 hover:text-white transition-colors underline"
          >
            필터 초기화
          </button>
        )}

        <span className="ml-auto text-xs text-slate-600">
          총 {filtered.length}건 거래
        </span>
      </div>

      {/* Table */}
      <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5">
        {loading ? (
          <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
            로딩 중…
          </div>
        ) : error ? (
          <div className="text-sm text-red-400 py-4">{error}</div>
        ) : (
          <TradeTable trades={paginated} />
        )}
      </div>

      {/* Load more */}
      {!loading && hasMore && (
        <div className="flex justify-center">
          <button
            onClick={() => setPage((p) => p + 1)}
            className="px-6 py-2 bg-slate-800 hover:bg-slate-700 text-sm text-slate-300 rounded-lg transition-colors"
          >
            더 보기 ({filtered.length - paginated.length}건 남음)
          </button>
        </div>
      )}
    </div>
  );
}
