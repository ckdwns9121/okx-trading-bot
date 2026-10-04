import { useTheme, type ThemePreference } from "@/lib/theme";
import { Badge, Card } from "@/components/ui";

const THEME_OPTIONS: { value: ThemePreference; label: string; desc: string }[] = [
  { value: "system", label: "시스템", desc: "macOS 설정을 따라갑니다" },
  { value: "light", label: "라이트", desc: "항상 밝은 화면" },
  { value: "dark", label: "다크", desc: "항상 어두운 화면" },
];

/** 미리보기 썸네일 — 선택지마다 실제 토큰 색으로 작은 화면을 그린다 */
const LIGHT_PREVIEW = { bg: "#ffffff", card: "#ffffff", line: "#e5e8eb", text: "#b0b8c1", accent: "#3182f6" };
const DARK_PREVIEW = { bg: "#121216", card: "#1b1b21", line: "#2a2a32", text: "#9298a3", accent: "#4c8dff" };
type PreviewPalette = typeof LIGHT_PREVIEW;

function Preview({ mode }: { mode: "light" | "dark" | "system" }) {
  const Half = ({ p, clip }: { p: PreviewPalette; clip?: string }) => (
    <div className="absolute inset-0" style={{ background: p.bg, clipPath: clip }}>
      <div className="absolute left-3 right-3 top-3 h-2 rounded-sm" style={{ background: p.text, opacity: 0.5 }} />
      <div className="absolute left-3 right-3 top-8 bottom-3 rounded-md border" style={{ background: p.card, borderColor: p.line }}>
        <div className="absolute left-2.5 top-2.5 w-10 h-1.5 rounded-sm" style={{ background: p.text }} />
        <div className="absolute left-2.5 top-6 w-16 h-2.5 rounded-sm" style={{ background: p.accent }} />
      </div>
    </div>
  );
  return (
    <div className="relative w-full aspect-[16/10] rounded-lg overflow-hidden border border-line">
      {mode === "system" ? (
        <>
          <Half p={LIGHT_PREVIEW} clip="polygon(0 0, 55% 0, 45% 100%, 0 100%)" />
          <Half p={DARK_PREVIEW} clip="polygon(55% 0, 100% 0, 100% 100%, 45% 100%)" />
        </>
      ) : (
        <Half p={mode === "dark" ? DARK_PREVIEW : LIGHT_PREVIEW} />
      )}
    </div>
  );
}

export default function ThemeTab() {
  const { preference, resolved, setPreference } = useTheme();
  return (
    <div className="space-y-6">
      <Card
        title="화면 테마"
        sub="테마는 이 기기에만 저장됩니다"
        action={<Badge tone="grey">{resolved === "dark" ? "지금 다크" : "지금 라이트"}</Badge>}
      >
        <div className="grid grid-cols-3 gap-4">
          {THEME_OPTIONS.map((o) => {
            const active = preference === o.value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => setPreference(o.value)}
                className={`text-left rounded-xl p-3 border-2 transition-colors ${
                  active ? "border-primary bg-primary-soft/40" : "border-line hover:border-line-strong"
                }`}
              >
                <Preview mode={o.value} />
                <div className="mt-3 flex items-center justify-between">
                  <div>
                    <p className="text-base font-semibold text-ink">{o.label}</p>
                    <p className="text-xs text-ink-muted mt-0.5">{o.desc}</p>
                  </div>
                  <span
                    className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                      active ? "border-primary bg-primary" : "border-line-strong"
                    }`}
                  >
                    {active && <span className="w-2 h-2 rounded-full bg-white" />}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
