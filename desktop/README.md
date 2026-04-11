# OKX Trading Desktop (Tauri + React + TypeScript)

이 디렉터리는 기존 `dashboard/`(Next.js) UI를 데스크탑 앱으로 이식한 Tauri 앱입니다.

## Prerequisites
- Node.js 20+
- Rust toolchain (`rustup`)
- Tauri 시스템 의존성
  - macOS: Xcode Command Line Tools
  - Linux: webkit2gtk 등 Tauri 공식 가이드 의존성

## Setup
```bash
cd desktop
cp .env.example .env
npm install
```

## Development
### 1) Bot API 실행 (프로젝트 루트)
```bash
docker compose up -d bot postgres
```

### 2) Desktop UI + Tauri 실행
```bash
cd desktop
npm run tauri:dev
```

> `tauri:dev`는 내부적으로 Vite dev server(`http://localhost:1420`)를 띄우고
> Tauri WebView에서 로드합니다.

## Build
```bash
cd desktop
npm run build         # React/Vite build
npm run tauri:build   # Native app build (toolchain 필요)
```

## Routes
- `/` 개요
- `/markets` 마켓
- `/backtest` 백테스트
- `/optimize` 최적화
- `/compare` 전략 비교
- `/selector` 전략 추천
- `/validate` 전략 검증
- `/trades` 거래 내역
- `/config` 설정

## Notes
- 기본 API 주소는 `http://localhost:8000` 입니다.
- 변경하려면 `.env`의 `VITE_API_BASE_URL` 값을 수정하세요.
