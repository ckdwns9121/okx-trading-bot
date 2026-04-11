import type { Order } from "@/lib/types";

interface Props {
  orders: Order[];
}

const STATUS_STYLES: Record<Order["status"], string> = {
  filled: "bg-green-900/50 text-green-400 border border-green-800",
  pending: "bg-yellow-900/50 text-yellow-400 border border-yellow-800",
  partial: "bg-blue-900/50 text-blue-400 border border-blue-800",
  cancelled: "bg-slate-700/50 text-slate-400 border border-slate-600",
  rejected: "bg-red-900/50 text-red-400 border border-red-800",
};

const STATUS_LABELS: Record<Order["status"], string> = {
  filled: "체결",
  pending: "대기 중",
  partial: "부분 체결",
  cancelled: "취소됨",
  rejected: "거부됨",
};

const SIDE_LABELS: Record<string, string> = {
  buy: "매수",
  sell: "매도",
};

const ORDER_TYPE_LABELS: Record<string, string> = {
  market: "시장가",
  limit: "지정가",
  stop: "스톱",
  stop_limit: "스톱 지정가",
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncate(s: string | null, len = 10): string {
  if (!s) return "—";
  return s.length > len ? `${s.slice(0, len)}…` : s;
}

export default function OrderTable({ orders }: Props) {
  if (orders.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-slate-500 text-sm">
        주문 내역 없음
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
            <th className="pb-3 pr-4 font-medium">ID</th>
            <th className="pb-3 pr-4 font-medium">거래쌍</th>
            <th className="pb-3 pr-4 font-medium">방향</th>
            <th className="pb-3 pr-4 font-medium">유형</th>
            <th className="pb-3 pr-4 font-medium">가격</th>
            <th className="pb-3 pr-4 font-medium">수량</th>
            <th className="pb-3 pr-4 font-medium">상태</th>
            <th className="pb-3 pr-4 font-medium">거래소 ID</th>
            <th className="pb-3 font-medium">시간</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {orders.map((o) => (
            <tr key={o.id} className="hover:bg-slate-800/30 transition-colors">
              <td className="py-2.5 pr-4 text-slate-500 text-xs font-mono">#{o.id}</td>
              <td className="py-2.5 pr-4 font-medium text-white">{o.pair}</td>
              <td className="py-2.5 pr-4">
                <span
                  className={`text-xs font-semibold ${
                    o.side === "buy" ? "text-green-400" : "text-red-400"
                  }`}
                >
                  {SIDE_LABELS[o.side] ?? o.side}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-slate-400 text-xs">{ORDER_TYPE_LABELS[o.order_type] ?? o.order_type}</td>
              <td className="py-2.5 pr-4 text-slate-300">
                {o.price !== null
                  ? `$${o.price.toLocaleString("en-US", { minimumFractionDigits: 2 })}`
                  : "시장가"}
              </td>
              <td className="py-2.5 pr-4 text-slate-300">{o.quantity}</td>
              <td className="py-2.5 pr-4">
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                    STATUS_STYLES[o.status]
                  }`}
                >
                  {STATUS_LABELS[o.status] ?? o.status}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-slate-500 text-xs font-mono">
                {truncate(o.exchange_order_id)}
              </td>
              <td className="py-2.5 text-slate-500 text-xs">{fmtDate(o.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
