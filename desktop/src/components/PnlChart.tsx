import type { Trade } from "@/lib/types";
import { fmtDateShort, fmtUsd } from "@/lib/format";
import { useChartColors } from "@/lib/chart";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Props {
  trades: Trade[];
  height?: number;
}

interface Point {
  ts: number;
  label: string;
  cum: number;
}

function buildCumulative(trades: Trade[]): Point[] {
  const closed = trades
    .filter((t) => t.status === "closed" && t.pnl !== null && t.exit_time !== null)
    .sort((a, b) => new Date(a.exit_time!).getTime() - new Date(b.exit_time!).getTime());
  let running = 0;
  return closed.map((t) => {
    running += t.pnl!;
    return { ts: new Date(t.exit_time!).getTime(), label: fmtDateShort(t.exit_time!), cum: Number(running.toFixed(2)) };
  });
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-surface border border-line rounded-md shadow-float px-3 py-2">
      <div className="text-xs text-ink-faint">{p.label}</div>
      <div className={`text-base font-bold tabular ${p.cum >= 0 ? "text-up" : "text-down"}`}>
        {fmtUsd(p.cum, { sign: true })}
      </div>
    </div>
  );
}

export default function PnlChart({ trades, height = 240 }: Props) {
  const data = buildCumulative(trades);
  const colors = useChartColors();

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-ink-faint text-sm" style={{ height }}>
        아직 청산된 거래가 없어요
      </div>
    );
  }

  const last = data[data.length - 1].cum;
  const color = last >= 0 ? colors.up : colors.down;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 12, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="pnl-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke={colors.grid} strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          tick={{ fill: colors.tick, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: colors.tick, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => fmtUsd(v, { digits: 0 })}
          width={64}
        />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: colors.tick, strokeDasharray: "3 3" }} />
        <ReferenceLine y={0} stroke={colors.grid} />
        <Area
          type="monotone"
          dataKey="cum"
          stroke={color}
          strokeWidth={2}
          fill="url(#pnl-fill)"
          dot={false}
          activeDot={{ r: 5, fill: color, stroke: colors.surface, strokeWidth: 2 }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
