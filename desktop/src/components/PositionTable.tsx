import type { Position } from "@/lib/types";

interface Props {
  positions: Position[];
}

function ArrowUp() {
  return (
    <svg className="w-3 h-3 inline mr-1 text-green-400" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 4l8 8H4z" />
    </svg>
  );
}

function ArrowDown() {
  return (
    <svg className="w-3 h-3 inline mr-1 text-red-400" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 20l-8-8h16z" />
    </svg>
  );
}

export default function PositionTable({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-slate-500 text-sm">
        포지션 없음
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
            <th className="pb-3 pr-4 font-medium">거래쌍</th>
            <th className="pb-3 pr-4 font-medium">방향</th>
            <th className="pb-3 pr-4 font-medium">진입가</th>
            <th className="pb-3 pr-4 font-medium">수량</th>
            <th className="pb-3 pr-4 font-medium">레버리지</th>
            <th className="pb-3 font-medium">미실현 손익</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {positions.map((pos) => {
            const isLong = pos.direction === "long";
            const pnlPositive = pos.unrealized_pnl >= 0;
            return (
              <tr key={pos.id} className="hover:bg-slate-800/30 transition-colors">
                <td className="py-3 pr-4 font-medium text-white">{pos.pair}</td>
                <td className="py-3 pr-4">
                  <span
                    className={`inline-flex items-center text-xs font-semibold ${
                      isLong ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {isLong ? <ArrowUp /> : <ArrowDown />}
                    {pos.direction === "long" ? "롱" : "숏"}
                  </span>
                </td>
                <td className="py-3 pr-4 text-slate-300">
                  ${pos.entry_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                </td>
                <td className="py-3 pr-4 text-slate-300">{pos.quantity}</td>
                <td className="py-3 pr-4 text-slate-300">{pos.leverage}x</td>
                <td
                  className={`py-3 font-semibold ${
                    pnlPositive ? "text-green-400" : "text-red-400"
                  }`}
                >
                  {pnlPositive ? "+" : ""}${pos.unrealized_pnl.toFixed(2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
