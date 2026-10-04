import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useState } from "react";
import { deltaClass, fmtPct, fmtUsd } from "@/lib/format";

/* ------------------------------------------------------------------ */
/* Layout primitives                                                   */
/* ------------------------------------------------------------------ */

export function Card({
  title,
  sub,
  action,
  children,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  sub?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      className={`bg-surface border border-line rounded-xl shadow-card ${padded ? "p-6" : ""} ${className}`}
    >
      {(title || action) && (
        <header className={`flex items-start justify-between gap-4 ${padded ? "mb-5" : "px-6 pt-6 mb-4"}`}>
          <div className="min-w-0">
            {title && <h2 className="text-lg font-bold text-ink tracking-tight">{title}</h2>}
            {sub && <p className="text-sm text-ink-muted mt-0.5">{sub}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  sub,
  action,
}: {
  title: ReactNode;
  sub?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-2xl font-bold text-ink tracking-tight">{title}</h1>
        {sub && <p className="text-sm text-ink-muted mt-1">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Controls                                                            */
/* ------------------------------------------------------------------ */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type ButtonSize = "sm" | "md";

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 font-semibold rounded-md transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed select-none";
  const sizes: Record<ButtonSize, string> = {
    sm: "h-8 px-3 text-sm",
    md: "h-10 px-4 text-base",
  };
  const variants: Record<ButtonVariant, string> = {
    primary: "bg-primary text-white hover:bg-primary-hover active:bg-blue-700",
    secondary: "bg-surface-muted text-ink-secondary hover:bg-surface-hover active:bg-surface-active",
    danger: "bg-danger text-white hover:bg-red-600",
    ghost: "bg-transparent text-ink-muted hover:bg-surface-muted hover:text-ink",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

/** 필터 칩 — 토스의 둥근 회색 필 */
export function Chip({
  active,
  onClick,
  children,
  count,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-9 px-3.5 rounded-full text-sm font-semibold transition-colors duration-150 whitespace-nowrap ${
        active
          ? "bg-ink text-bg"
          : "bg-surface-muted text-ink-secondary hover:bg-surface-hover"
      }`}
    >
      {children}
      {count !== undefined && (
        <span className={`ml-1.5 tabular ${active ? "text-ink-faint" : "text-ink-faint"}`}>{count}</span>
      )}
    </button>
  );
}

/** 세그먼트 컨트롤 — 회색 트랙 위에 흰색 선택 탭 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex p-1 bg-surface-muted rounded-md">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={`h-8 px-3.5 rounded-sm text-sm font-semibold transition-all duration-150 ${
              active ? "bg-surface text-ink shadow-card" : "text-ink-muted hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "검색",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <svg
        className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint pointer-events-none"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.2}
        strokeLinecap="round"
      >
        <circle cx="11" cy="11" r="7" />
        <line x1="20" y1="20" x2="16.5" y2="16.5" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-10 w-full bg-surface-muted rounded-md pl-10 pr-9 text-base text-ink placeholder:text-ink-faint focus:outline-none focus:bg-surface focus:ring-2 focus:ring-blue-200 transition-colors"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="지우기"
          className="absolute right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full bg-ink-disabled text-bg flex items-center justify-center hover:bg-ink-faint"
        >
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round">
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="18" y1="6" x2="6" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}

export function Select({
  value,
  onChange,
  children,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`h-9 bg-surface-muted rounded-md pl-3 text-sm font-medium text-ink-secondary focus:outline-none focus:ring-2 focus:ring-blue-200 ${className}`}
    >
      {children}
    </select>
  );
}

/* ------------------------------------------------------------------ */
/* Data display                                                        */
/* ------------------------------------------------------------------ */

type Tone = "blue" | "red" | "green" | "orange" | "grey";

export function Badge({ tone = "grey", children }: { tone?: Tone; children: ReactNode }) {
  const tones: Record<Tone, string> = {
    blue: "bg-primary-soft text-primary-strong",
    red: "bg-danger-soft text-danger-strong",
    green: "bg-ok-soft text-ok-strong",
    orange: "bg-warn-soft text-warn-strong",
    grey: "bg-surface-muted text-ink-muted",
  };
  return (
    <span className={`inline-flex items-center h-6 px-2 rounded-sm text-xs font-semibold whitespace-nowrap ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** 상태 점 + 라벨 */
export function StatusDot({ ok, pulse = false }: { ok: boolean; pulse?: boolean }) {
  return (
    <span className="relative inline-flex w-2 h-2">
      {pulse && (
        <span className={`absolute inset-0 rounded-full ${ok ? "bg-ok" : "bg-danger"} opacity-60 animate-ping`} />
      )}
      <span className={`relative inline-flex w-2 h-2 rounded-full ${ok ? "bg-ok" : "bg-danger"}`} />
    </span>
  );
}

/**
 * 변동 표기 — 토스처럼 "+319.27 (1.18%)" 한 줄.
 * 금액(abs)과 비율(pct) 중 있는 것만 보여준다.
 */
export function Delta({
  abs,
  pct,
  digits = 2,
  className = "",
  size = "sm",
}: {
  abs?: number | null;
  pct?: number | null;
  digits?: number;
  className?: string;
  size?: "sm" | "base" | "lg";
}) {
  const ref = pct ?? abs ?? 0;
  const sizeCls = size === "lg" ? "text-lg" : size === "base" ? "text-base" : "text-sm";
  const parts: string[] = [];
  if (abs !== undefined && abs !== null) parts.push(fmtUsd(abs, { sign: true, digits }));
  if (pct !== undefined && pct !== null) {
    const p = fmtPct(Math.abs(pct), { sign: false });
    parts.push(abs !== undefined && abs !== null ? `(${p})` : `${pct > 0 ? "+" : pct < 0 ? "-" : ""}${p}`);
  }
  return (
    <span className={`font-semibold tabular ${sizeCls} ${deltaClass(ref)} ${className}`}>
      {parts.join(" ")}
    </span>
  );
}

/** 인덱스 카드 스타일의 큰 숫자 타일 */
export function StatTile({
  label,
  value,
  delta,
  sub,
  accent,
}: {
  label: ReactNode;
  value: ReactNode;
  delta?: ReactNode;
  sub?: ReactNode;
  accent?: ReactNode;
}) {
  return (
    <div className="bg-surface border border-line rounded-xl shadow-card p-5 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-ink-muted truncate">{label}</p>
        {accent}
      </div>
      <p className="mt-2 text-2xl font-bold text-ink tabular tracking-tight truncate">{value}</p>
      <div className="mt-1 flex items-center gap-2 min-h-[20px]">
        {delta}
        {sub && <span className="text-xs text-ink-faint truncate">{sub}</span>}
      </div>
    </div>
  );
}

export function CoinAvatar({
  iconUrl,
  symbol,
  size = 36,
}: {
  iconUrl: string;
  symbol: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size };
  if (failed || !iconUrl) {
    return (
      <div
        style={style}
        className="rounded-full bg-surface-muted text-ink-secondary flex items-center justify-center shrink-0 font-bold text-sm"
      >
        {symbol.slice(0, 1)}
      </div>
    );
  }
  return (
    <img
      src={iconUrl}
      alt=""
      width={size}
      height={size}
      style={style}
      loading="lazy"
      className="rounded-full shrink-0 object-cover bg-surface-muted"
      onError={() => setFailed(true)}
    />
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-sm bg-surface-muted ${className}`} />;
}

export function Empty({ title, sub, className = "" }: { title: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-14 ${className}`}>
      <div className="w-12 h-12 rounded-full bg-surface-muted flex items-center justify-center mb-3">
        <svg className="w-5 h-5 text-ink-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <path d="M4 7h16M4 12h10M4 17h7" />
        </svg>
      </div>
      <p className="text-base font-semibold text-ink-secondary">{title}</p>
      {sub && <p className="text-sm text-ink-faint mt-1">{sub}</p>}
    </div>
  );
}

export function Notice({
  tone = "blue",
  title,
  children,
  action,
}: {
  tone?: "blue" | "red" | "orange";
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    blue: "bg-primary-soft text-primary-strong",
    red: "bg-danger-soft text-danger-strong",
    orange: "bg-warn-soft text-warn-strong",
  } as const;
  return (
    <div className={`flex items-start gap-3 rounded-lg px-4 py-3 ${tones[tone]}`}>
      <svg className="w-5 h-5 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
        <circle cx="12" cy="12" r="9" />
        <line x1="12" y1="8" x2="12" y2="12.5" />
        <circle cx="12" cy="16" r="0.6" fill="currentColor" />
      </svg>
      <div className="flex-1 min-w-0">
        <p className="text-base font-semibold">{title}</p>
        {children && <div className="text-sm opacity-90 mt-0.5">{children}</div>}
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Table                                                               */
/* ------------------------------------------------------------------ */

export function Th({
  children,
  align = "left",
  className = "",
  onClick,
  active,
  dir,
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
  onClick?: () => void;
  active?: boolean;
  dir?: "asc" | "desc";
}) {
  const clickable = !!onClick;
  return (
    <th
      onClick={onClick}
      className={`h-11 px-4 text-sm font-medium whitespace-nowrap ${align === "right" ? "text-right" : "text-left"} ${
        clickable ? "cursor-pointer select-none hover:text-ink" : ""
      } ${active ? "text-ink" : "text-ink-muted"} ${className}`}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {clickable && (
          <span className={`text-2xs ${active ? "text-ink" : "text-ink-disabled"}`}>
            {active ? (dir === "asc" ? "▲" : "▼") : "▼"}
          </span>
        )}
      </span>
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <td className={`px-4 py-3.5 text-base tabular ${align === "right" ? "text-right" : "text-left"} ${className}`}>
      {children}
    </td>
  );
}
