import { useEffect, useState } from "react";
import { getTradingLogs } from "@/lib/api";
import type { TradingLogEvent } from "@/lib/types";
import { fmtTime } from "@/lib/format";
import { Badge, Card, Empty, SearchInput } from "@/components/ui";

const REFRESH_MS = 5_000;

function logTone(level: string): "red" | "orange" | "grey" {
  if (level === "error") return "red";
  if (level === "warning") return "orange";
  return "grey";
}

function logText(log: TradingLogEvent): string {
  if (typeof log.message === "string" && log.message.trim()) return log.message;
  if (log.details && Object.keys(log.details).length > 0) return JSON.stringify(log.details);
  return "-";
}

export default function LogsTab() {
  const [logs, setLogs] = useState<TradingLogEvent[]>([]);
  const [level, setLevel] = useState<"all" | "warning" | "error">("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const rows = await getTradingLogs(200);
        if (alive) setLogs(rows);
      } catch {
        /* 일시적 오류는 이전 로그 유지 */
      }
    }
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const q = query.trim().toLowerCase();
  const visible = logs
    .filter((l) => level === "all" || l.level === "error" || (level === "warning" && l.level === "warning"))
    .filter((l) => !q || `${l.event} ${l.pair ?? ""} ${l.strategy ?? ""} ${logText(l)}`.toLowerCase().includes(q))
    .slice()
    .reverse();

  const errorCount = logs.filter((l) => l.level === "error").length;
  const warnCount = logs.filter((l) => l.level === "warning").length;

  return (
    <Card
      padded={false}
      title="실시간 로그"
      sub={`최근 ${logs.length}건 · 오류 ${errorCount} · 경고 ${warnCount}`}
      action={
        <div className="flex items-center gap-2">
          <SearchInput value={query} onChange={setQuery} placeholder="이벤트·종목 검색" className="w-56" />
          <div className="inline-flex p-1 bg-surface-muted rounded-md">
            {(["all", "warning", "error"] as const).map((lv) => (
              <button
                key={lv}
                type="button"
                onClick={() => setLevel(lv)}
                className={`h-8 px-3 rounded-sm text-sm font-semibold transition-all ${
                  level === lv ? "bg-surface text-ink shadow-card" : "text-ink-muted hover:text-ink"
                }`}
              >
                {lv === "all" ? "전체" : lv === "warning" ? "경고 이상" : "오류"}
              </button>
            ))}
          </div>
        </div>
      }
    >
      {visible.length === 0 ? (
        <Empty title="표시할 로그가 없어요" sub={q ? "검색어를 바꿔보세요" : "트레이더가 돌기 시작하면 이벤트가 쌓입니다"} />
      ) : (
        <div className="max-h-[640px] overflow-y-auto border-t border-line">
          {visible.map((log) => (
            <div key={log.id} className="px-6 py-3 border-b border-line last:border-0 grid grid-cols-[72px_64px_1fr] gap-3 items-start hover:bg-bg-subtle">
              <span className="text-sm text-ink-faint tabular pt-0.5">{fmtTime(log.timestamp)}</span>
              <Badge tone={logTone(log.level)}>{log.level === "error" ? "오류" : log.level === "warning" ? "경고" : "정보"}</Badge>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">
                  {log.event}
                  {(log.pair || log.strategy || log.timeframe) && (
                    <span className="font-medium text-ink-faint"> · {[log.pair, log.strategy, log.timeframe].filter(Boolean).join(" / ")}</span>
                  )}
                </p>
                <p className="text-sm text-ink-muted break-all mt-0.5">{logText(log)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
