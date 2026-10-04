import type { Position } from "@/lib/types";
import { deltaClass, fmtDateTime, fmtPrice, fmtUsd } from "@/lib/format";
import { Badge, Empty, Td, Th } from "@/components/ui";

interface Props {
  positions: Position[];
}

export default function PositionTable({ positions }: Props) {
  if (positions.length === 0) {
    return <Empty title="열린 포지션이 없어요" sub="새 신호가 오면 여기에 표시됩니다" className="py-10" />;
  }

  return (
    <div className="overflow-x-auto -mx-6">
      <table className="w-full min-w-[720px]">
        <thead>
          <tr className="border-b border-line">
            <Th className="pl-6">종목</Th>
            <Th>방향</Th>
            <Th align="right">진입가</Th>
            <Th align="right">수량</Th>
            <Th align="right">레버리지</Th>
            <Th align="right">평가 손익</Th>
            <Th align="right" className="pr-6">진입 시각</Th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const isLong = pos.direction === "long";
            return (
              <tr key={pos.id} className="border-b border-line last:border-0 hover:bg-bg-subtle transition-colors">
                <Td className="pl-6 font-semibold text-ink">{pos.pair}</Td>
                <Td>
                  <Badge tone={isLong ? "red" : "blue"}>{isLong ? "롱" : "숏"}</Badge>
                </Td>
                <Td align="right" className="text-ink-secondary">{fmtPrice(pos.entry_price)}</Td>
                <Td align="right" className="text-ink-secondary">{pos.quantity}</Td>
                <Td align="right" className="text-ink-secondary">{pos.leverage}x</Td>
                <Td align="right" className={`font-semibold ${deltaClass(pos.unrealized_pnl)}`}>
                  {fmtUsd(pos.unrealized_pnl, { sign: true })}
                </Td>
                <Td align="right" className="pr-6 text-ink-faint text-sm">{fmtDateTime(pos.opened_at)}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
