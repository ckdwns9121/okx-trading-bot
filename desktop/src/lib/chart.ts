import { useMemo } from "react";
import { useTheme } from "@/lib/theme";

/**
 * recharts는 색을 SVG 속성으로 박기 때문에 CSS 변수 문자열을 그대로 넘기면
 * 그라데이션 stop 같은 곳에서 깨진다. 테마가 바뀔 때마다 실제 값을 읽어 온다.
 */
export function useChartColors() {
  const { resolved } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    return {
      up: read("--color-up", "#f04452"),
      down: read("--color-down", "#3182f6"),
      primary: read("--color-primary", "#3182f6"),
      grid: read("--chart-grid", "#e5e8eb"),
      tick: read("--chart-tick", "#8b95a1"),
      muted: read("--color-ink-faint", "#8b95a1"),
      surface: read("--color-surface", "#ffffff"),
    };
    // resolved가 바뀌면 data-theme가 이미 적용된 뒤라 새 값이 읽힌다
  }, [resolved]);
}
