import type { EquityPoint } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { useChartColors } from "@/lib/chart";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Props {
  points: EquityPoint[];
  startingEquity: number;
  height?: number;
}

interface Row {
  label: string;
  strategy: number;
  buyHold: number | null;
}

function toRows(points: EquityPoint[]): Row[] {
  return points.map((p) => {
    const d = new Date(Number(p.ts));
    const label = Number.isNaN(d.getTime())
      ? p.ts
      : d.toLocaleDateString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric" });
    return { label, strategy: p.equity, buyHold: p.buy_hold ?? null };
  });
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { payload: Row }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-surface border border-line rounded-md shadow-float px-3 py-2 text-sm">
      <div className="text-xs text-ink-faint mb-1">{label}</div>
      <div className="flex items-center justify-between gap-6">
        <span className="text-ink-muted">전략</span>
        <span className="font-semibold tabular text-ink">{fmtUsd(row.strategy, { digits: 0 })}</span>
      </div>
      {row.buyHold !== null && (
        <div className="flex items-center justify-between gap-6">
          <span className="text-ink-muted">매수 후 보유</span>
          <span className="font-semibold tabular text-ink-secondary">{fmtUsd(row.buyHold, { digits: 0 })}</span>
        </div>
      )}
    </div>
  );
}

/** 전략 자산곡선 vs 매수-보유 벤치마크. 두 시리즈라 범례는 항상 표시. */
export default function EquityChart({ points, startingEquity, height = 280 }: Props) {
  const colors = useChartColors();
  const rows = toRows(points);
  const hasBenchmark = rows.some((r) => r.buyHold !== null);

  return (
    <div>
      <div className="flex items-center gap-4 mb-3 text-sm">
        <span className="inline-flex items-center gap-2 text-ink-secondary">
          <span className="w-4 h-0.5 rounded-full" style={{ background: colors.primary }} />
          전략
        </span>
        {hasBenchmark && (
          <span className="inline-flex items-center gap-2 text-ink-muted">
            <span className="w-4 h-0.5 rounded-full border-t-2 border-dashed" style={{ borderColor: colors.muted }} />
            매수 후 보유
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={colors.grid} strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            tick={{ fill: colors.tick, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={56}
          />
          <YAxis
            tick={{ fill: colors.tick, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => fmtUsd(v, { digits: 0 })}
            width={72}
            domain={["auto", "auto"]}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: colors.tick, strokeDasharray: "3 3" }} />
          <ReferenceLine y={startingEquity} stroke={colors.grid} />
          {hasBenchmark && (
            <Line
              type="monotone"
              dataKey="buyHold"
              stroke={colors.muted}
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
          <Line
            type="monotone"
            dataKey="strategy"
            stroke={colors.primary}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5, fill: colors.primary, stroke: colors.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
