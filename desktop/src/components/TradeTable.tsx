import type { Trade } from "@/lib/types";

interface Props {
  trades: Trade[];
}

function fmtPrice(value: number | null): string {
  if (value === null) return "—";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TradeTable({ trades }: Props) {
  const sorted = [...trades].sort(
    (a, b) => new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()
  );

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-slate-500 text-sm">
        거래 내역 없음
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
            <th className="pb-3 pr-4 font-medium">거래쌍</th>
            <th className="pb-3 pr-4 font-medium">전략</th>
            <th className="pb-3 pr-4 font-medium">방향</th>
            <th className="pb-3 pr-4 font-medium">진입가</th>
            <th className="pb-3 pr-4 font-medium">청산가</th>
            <th className="pb-3 pr-4 font-medium">손익</th>
            <th className="pb-3 pr-4 font-medium">손익%</th>
            <th className="pb-3 pr-4 font-medium">레버리지</th>
            <th className="pb-3 font-medium">시간</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {sorted.map((t) => {
            const pnlPos = t.pnl !== null && t.pnl >= 0;
            const isLong = t.direction === "long";
            return (
              <tr key={t.id} className="hover:bg-slate-800/30 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-white">{t.pair}</td>
                <td className="py-2.5 pr-4 text-slate-400 text-xs">{t.strategy_name}</td>
                <td className="py-2.5 pr-4">
                  <span
                    className={`text-xs font-semibold ${
                      isLong ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {t.direction === "long" ? "롱" : "숏"}
                  </span>
                </td>
                <td className="py-2.5 pr-4 text-slate-300">{fmtPrice(t.entry_price)}</td>
                <td className="py-2.5 pr-4 text-slate-300">{fmtPrice(t.exit_price)}</td>
                <td
                  className={`py-2.5 pr-4 font-semibold ${
                    t.pnl === null
                      ? "text-slate-400"
                      : pnlPos
                      ? "text-green-400"
                      : "text-red-400"
                  }`}
                >
                  {t.pnl === null ? "—" : `${t.pnl >= 0 ? "+" : "-"}$${Math.abs(t.pnl).toFixed(2)}`}
                </td>
                <td
                  className={`py-2.5 pr-4 font-semibold ${
                    t.pnl_pct === null
                      ? "text-slate-400"
                      : t.pnl_pct >= 0
                      ? "text-green-400"
                      : "text-red-400"
                  }`}
                >
                  {t.pnl_pct === null
                    ? "—"
                    : `${t.pnl_pct >= 0 ? "+" : ""}${t.pnl_pct.toFixed(2)}%`}
                </td>
                <td className="py-2.5 pr-4 text-slate-300">{t.leverage}x</td>
                <td className="py-2.5 text-slate-500 text-xs">{fmtDate(t.entry_time)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
