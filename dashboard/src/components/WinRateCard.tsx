interface Props {
  win_rate: number;
  trade_count: number;
  realized_pnl: number;
}

export default function WinRateCard({ win_rate, trade_count, realized_pnl }: Props) {
  const pct = Math.round(win_rate * 100);
  const pnlPositive = realized_pnl >= 0;

  // Simple circular ring via SVG
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (pct / 100) * circumference;
  const ringColor = pct >= 50 ? "#22c55e" : "#ef4444";

  return (
    <div className="bg-[#161b27] border border-slate-800 rounded-xl p-5 flex flex-col gap-4">
      <p className="text-sm font-medium text-slate-400">승률</p>

      <div className="flex items-center gap-6">
        {/* Ring */}
        <div className="relative shrink-0">
          <svg width={88} height={88} className="-rotate-90">
            <circle
              cx={44}
              cy={44}
              r={radius}
              fill="none"
              stroke="#1e293b"
              strokeWidth={8}
            />
            <circle
              cx={44}
              cy={44}
              r={radius}
              fill="none"
              stroke={ringColor}
              strokeWidth={8}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              style={{ transition: "stroke-dashoffset 0.6s ease" }}
            />
          </svg>
          <span
            className="absolute inset-0 flex items-center justify-center text-lg font-bold"
            style={{ color: ringColor }}
          >
            {pct}%
          </span>
        </div>

        {/* Stats */}
        <div className="space-y-2">
          <div>
            <p className="text-xs text-slate-500">총 거래 수</p>
            <p className="text-xl font-semibold text-white">{trade_count}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">실현 손익</p>
            <p
              className={`text-xl font-semibold ${
                pnlPositive ? "text-green-400" : "text-red-400"
              }`}
            >
              {pnlPositive ? "+" : ""}${realized_pnl.toFixed(2)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
