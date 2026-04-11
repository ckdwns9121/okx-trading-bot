"use client";

import type { Trade } from "@/lib/types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

interface Props {
  trades: Trade[];
}

interface DataPoint {
  date: string;
  cumPnl: number;
}

function buildCumulativePnl(trades: Trade[]): DataPoint[] {
  const closed = trades
    .filter((t) => t.status === "closed" && t.pnl !== null && t.exit_time !== null)
    .sort((a, b) => new Date(a.exit_time!).getTime() - new Date(b.exit_time!).getTime());

  let running = 0;
  return closed.map((t) => {
    running += t.pnl!;
    return {
      date: new Date(t.exit_time!).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      cumPnl: parseFloat(running.toFixed(2)),
    };
  });
}

function formatUsd(value: number) {
  return `$${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

export default function PnlChart({ trades }: Props) {
  const data = buildCumulativePnl(trades);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
        완료된 거래 내역 없음
      </div>
    );
  }

  const lastPnl = data[data.length - 1].cumPnl;
  const lineColor = lastPnl >= 0 ? "#22c55e" : "#ef4444";

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <XAxis
          dataKey="date"
          tick={{ fill: "#94a3b8", fontSize: 11 }}
          axisLine={{ stroke: "#334155" }}
          tickLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fill: "#94a3b8", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `$${v}`}
          width={60}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "#94a3b8" }}
          itemStyle={{ color: lineColor }}
          formatter={(value: number) => [formatUsd(value), "누적 손익"]}
        />
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
        <Line
          type="monotone"
          dataKey="cumPnl"
          stroke={lineColor}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: lineColor }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
