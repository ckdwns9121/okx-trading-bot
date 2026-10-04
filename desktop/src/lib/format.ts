/** 숫자/시간 포맷 — 모든 페이지가 같은 규칙으로 표기하도록 한 곳에 모은다. */

export function fmtPrice(value: number): string {
  if (!Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 4 : abs >= 0.01 ? 4 : 8;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: digits >= 4 ? 2 : digits,
    maximumFractionDigits: digits,
  })}`;
}

export function fmtUsd(value: number, { sign = false, digits = 2 } = {}): string {
  if (!Number.isFinite(value)) return "-";
  const prefix = sign && value > 0 ? "+" : value < 0 ? "-" : "";
  return `${prefix}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function fmtCompactUsd(value: number): string {
  if (!Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

export function fmtPct(value: number | null | undefined, { sign = true, digits = 2 } = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const prefix = sign && value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(digits)}%`;
}

export function fmtInt(value: number): string {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDateShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" });
}

/** 상승/하락/보합 → 텍스트 색 클래스 (국내 관례: 상승 빨강, 하락 파랑) */
export function deltaClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) return "text-flat";
  return value > 0 ? "text-up" : "text-down";
}

export function deltaSoftClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) return "bg-surface-muted text-flat";
  return value > 0 ? "bg-up-soft text-up" : "bg-down-soft text-down";
}
