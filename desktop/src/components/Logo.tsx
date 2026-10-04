/**
 * 서비스 로고 마크.
 * 토스 블루 그라데이션 라운드 사각형 위에 우상향 추세선 — "안전하게 오른다"는 인상.
 * SVG 하나로 그려서 어떤 크기에서도 선명하다. 앱 아이콘(src-tauri/icons)도 같은 도형에서 뽑는다.
 */
export function LogoMark({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      role="img"
      aria-label="OKX 봇 로고"
    >
      <defs>
        <linearGradient id="okxbot-bg" x1="8" y1="6" x2="58" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#5B9CFF" />
          <stop offset="1" stopColor="#1B64DA" />
        </linearGradient>
        <linearGradient id="okxbot-glow" x1="32" y1="64" x2="32" y2="20" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.18" />
        </linearGradient>
      </defs>

      {/* 바탕 */}
      <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#okxbot-bg)" />
      {/* 추세선 아래 은은한 영역 */}
      <path d="M14 46 L26 34 L34 40 L50 22 L50 50 L14 50 Z" fill="url(#okxbot-glow)" />
      {/* 추세선 */}
      <path
        d="M14 46 L26 34 L34 40 L50 22"
        stroke="#ffffff"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 화살표 머리 */}
      <path d="M40 22 H50 V32" stroke="#ffffff" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <LogoMark size={26} />
      {!compact && <span className="text-base font-bold tracking-tight text-ink leading-none">OKX 봇</span>}
    </div>
  );
}
