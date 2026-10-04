import type { Config } from "tailwindcss";

/**
 * Tailwind는 CSS 변수(globals.css)를 그대로 노출만 한다.
 * 색 값은 한 곳(globals.css)에서만 정의하고 여기서는 이름만 붙인다.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        grey: {
          50: "var(--grey-50)",
          100: "var(--grey-100)",
          200: "var(--grey-200)",
          300: "var(--grey-300)",
          400: "var(--grey-400)",
          500: "var(--grey-500)",
          600: "var(--grey-600)",
          700: "var(--grey-700)",
          800: "var(--grey-800)",
          900: "var(--grey-900)",
        },
        blue: {
          50: "var(--blue-50)",
          100: "var(--blue-100)",
          200: "var(--blue-200)",
          500: "var(--blue-500)",
          600: "var(--blue-600)",
          700: "var(--blue-700)",
        },
        red: {
          50: "var(--red-50)",
          100: "var(--red-100)",
          500: "var(--red-500)",
          600: "var(--red-600)",
        },
        green: {
          50: "var(--green-50)",
          500: "var(--green-500)",
          600: "var(--green-600)",
        },
        orange: {
          50: "var(--orange-50)",
          500: "var(--orange-500)",
          600: "var(--orange-600)",
        },

        // semantic
        bg: "var(--color-bg)",
        "bg-subtle": "var(--color-bg-subtle)",
        surface: "var(--color-surface)",
        "surface-muted": "var(--color-surface-muted)",
        "surface-hover": "var(--color-surface-hover)",
        "surface-active": "var(--color-surface-active)",
        line: "var(--color-line)",
        "line-strong": "var(--color-line-strong)",

        ink: "var(--color-ink)",
        "ink-secondary": "var(--color-ink-secondary)",
        "ink-muted": "var(--color-ink-muted)",
        "ink-faint": "var(--color-ink-faint)",
        "ink-disabled": "var(--color-ink-disabled)",

        primary: "var(--color-primary)",
        "primary-hover": "var(--color-primary-hover)",
        "primary-soft": "var(--color-primary-soft)",
        "primary-strong": "var(--color-primary-strong)",
        danger: "var(--color-danger)",
        "danger-soft": "var(--color-danger-soft)",
        "danger-strong": "var(--color-danger-strong)",
        ok: "var(--color-ok)",
        "ok-soft": "var(--color-ok-soft)",
        "ok-strong": "var(--color-ok-strong)",
        warn: "var(--color-warn)",
        "warn-soft": "var(--color-warn-soft)",
        "warn-strong": "var(--color-warn-strong)",

        up: "var(--color-up)",
        "up-soft": "var(--color-up-soft)",
        down: "var(--color-down)",
        "down-soft": "var(--color-down-soft)",
        flat: "var(--color-flat)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        float: "var(--shadow-float)",
      },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "Apple SD Gothic Neo",
          "Noto Sans KR",
          "sans-serif",
        ],
      },
      fontSize: {
        // 토스 타이포 스케일에 가깝게 — 본문 15px
        "2xs": ["11px", { lineHeight: "16px" }],
        xs: ["12px", { lineHeight: "18px" }],
        sm: ["13px", { lineHeight: "20px" }],
        base: ["15px", { lineHeight: "22px" }],
        lg: ["17px", { lineHeight: "24px" }],
        xl: ["20px", { lineHeight: "28px" }],
        "2xl": ["24px", { lineHeight: "32px" }],
        "3xl": ["28px", { lineHeight: "36px" }],
        "4xl": ["34px", { lineHeight: "42px" }],
      },
    },
  },
  plugins: [],
};

export default config;
