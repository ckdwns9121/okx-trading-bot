import type { Trade } from "@/lib/types";
import { deltaClass, fmtDateTime, fmtPct, fmtPrice, fmtUsd } from "@/lib/format";
import { Badge, Empty, Td, Th } from "@/components/ui";

interface Props {
  trades: Trade[];
}

export default function TradeTable({ trades }: Props) {
  const sorted = [...trades].sort(
    (a, b) => new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime(),
  );

  if (sorted.length === 0) {
    return <Empty title="거래 내역이 없어요" sub="체결이 생기면 여기에 쌓입니다" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px]">
        <thead>
          <tr className="border-b border-line">
            <Th className="pl-6">종목</Th>
            <Th>전략</Th>
            <Th>방향</Th>
            <Th align="right">진입가</Th>
            <Th align="right">청산가</Th>
            <Th align="right">손익</Th>
            <Th align="right">수익률</Th>
            <Th align="right">레버리지</Th>
            <Th align="right" className="pr-6">진입 시각</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => {
            const isLong = t.direction === "long";
            const open = t.status === "open";
            return (
              <tr key={t.id} className="border-b border-line last:border-0 hover:bg-bg-subtle transition-colors">
                <Td className="pl-6 font-semibold text-ink">{t.pair}</Td>
                <Td className="text-sm text-ink-muted max-w-[200px] truncate">{t.strategy_name}</Td>
                <Td>
                  <span className="inline-flex items-center gap-1.5">
                    <Badge tone={isLong ? "red" : "blue"}>{isLong ? "롱" : "숏"}</Badge>
                    {open && <Badge tone="grey">보유 중</Badge>}
                  </span>
                </Td>
                <Td align="right" className="text-ink-secondary">{fmtPrice(t.entry_price)}</Td>
                <Td align="right" className="text-ink-secondary">{t.exit_price === null ? "-" : fmtPrice(t.exit_price)}</Td>
                <Td align="right" className={`font-semibold ${deltaClass(t.pnl)}`}>
                  {t.pnl === null ? "-" : fmtUsd(t.pnl, { sign: true })}
                </Td>
                <Td align="right" className={`font-semibold ${deltaClass(t.pnl_pct)}`}>
                  {fmtPct(t.pnl_pct)}
                </Td>
                <Td align="right" className="text-ink-secondary">{t.leverage}x</Td>
                <Td align="right" className="pr-6 text-ink-faint text-sm">{fmtDateTime(t.entry_time)}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
