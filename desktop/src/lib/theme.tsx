import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "okxbot.theme";
const MEDIA = "(prefers-color-scheme: dark)";

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): ThemePreference {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* 저장소 접근 불가(프라이빗 모드 등)면 시스템 기본 */
  }
  return "system";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia(MEDIA).matches ? "dark" : "light";
}

/** 개발 중 스크린샷용: `#/path?theme=dark` 로 강제. 프로덕션 빌드에선 무시된다. */
function devOverride(): ThemePreference | null {
  if (!import.meta.env.DEV) return null;
  const q = window.location.hash.split("?")[1];
  const v = q ? new URLSearchParams(q).get("theme") : null;
  return v === "light" || v === "dark" ? v : null;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => devOverride() ?? readStored());
  const [system, setSystem] = useState<ResolvedTheme>(() => systemTheme());

  // OS 테마 변화 추적 (시스템 모드일 때만 결과에 영향)
  useEffect(() => {
    const mq = window.matchMedia(MEDIA);
    const onChange = (e: MediaQueryListEvent) => setSystem(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const resolved: ResolvedTheme = preference === "system" ? system : preference;

  // <html data-theme> 한 곳만 바꾸면 CSS 변수가 통째로 바뀐다
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
  }, [resolved]);

  const setPreference = useCallback((p: ThemePreference) => {
    setPreferenceState(p);
    try {
      window.localStorage.setItem(STORAGE_KEY, p);
    } catch {
      /* 저장 실패해도 현재 세션엔 적용된다 */
    }
  }, []);

  const value = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
