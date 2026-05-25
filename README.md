# OKX Trading Bot (Demo/Live) + Dashboard + Desktop

OKX 선물(스왑) 자동매매를 위한 통합 프로젝트입니다.

- **Bot API (FastAPI)**: Funding/OI 데모 트레이더 상태, 포지션/거래/로그 관리
- **Web Dashboard (Next.js)**: 실시간 상태, 마켓, 거래 내역, 런타임 진단 UI
- **Desktop App (Tauri + React + TS)**: 데스크탑 환경에서 동일 기능 사용
- **DB (PostgreSQL)**: 거래, 런타임 이벤트 로그, 연구용 시장 스냅샷 영구 저장

> ⚠️ 투자 손실 위험이 있습니다. 본 프로젝트는 학습/실험 목적이며 투자 조언이 아닙니다.

---

## 1) 프로젝트 구조

```text
.
├─ bot/           # FastAPI + Funding/OI 연구/데모 실행 + OKX 연동
├─ dashboard/     # Next.js 웹 대시보드
├─ desktop/       # Tauri 데스크탑 앱
├─ docs/          # 운영/전략 문서
├─ docker-compose.yml
└─ .env(.example)
```

---

## 2) 빠른 실행

### 2-1. 환경변수 준비

```bash
cp .env.example .env
```

핵심값:

- `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSPHRASE`
- `OKX_MODE=demo` (데모계좌)
- `DATABASE_URL`
- (선택) 텔레그램 알림
  - `TELEGRAM_NOTIFICATIONS_ENABLED=true`
  - `TELEGRAM_BOT_TOKEN=...`
  - `TELEGRAM_CHAT_ID=...`
  - `TELEGRAM_COMMANDS_ENABLED=true`

### 2-2. 전체 스택 실행

```bash
docker compose up -d --build
```

접속:

- Dashboard: http://127.0.0.1:3000
- Bot API: http://127.0.0.1:8000
- OpenAPI: http://127.0.0.1:8000/docs

### 2-3. Crowded Perp Unwind Research

현재 연구 경로는 전략 실행이 아니라 OKX 공개 데이터 수집과 이벤트 스터디입니다.
promotion gate를 통과하기 전까지 전략 파일을 추가하거나 자동 등록하지 않습니다.

```bash
# OKX public endpoint contract 문서
sed -n '1,220p' docs/research/okx_public_data_contract.md

# 공개 데이터 dry-run 스냅샷
cd bot
.venv/bin/python scripts/collect_crowded_perp_snapshots.py --dry-run --duration 30 --interval 10

# synthetic event-study dry-run
.venv/bin/python scripts/run_crowded_unwind_event_study.py --dry-run

# DB에 저장된 snapshot 기반 event-study
.venv/bin/python scripts/run_crowded_unwind_event_study.py --inst BTC-USDT-SWAP --limit 5000
```

연구 계획과 검증 기준은 `.omx/plans/prd-crowded-perp-unwind-pipeline.md` 및
`.omx/plans/test-spec-crowded-perp-unwind-pipeline.md`에 기록되어 있습니다.

### 2-4. Funding/OI Demo Trader 상태 확인

Legacy 캔들 전략 엔진, 백테스트 API, 최적화 API, 전략 설정 API는 제거되었습니다.
현재 실행/관찰 대상은 Funding/OI 데모 트레이더입니다.

```bash
# Funding/OI 데모 트레이더 상태
curl http://127.0.0.1:8000/api/trading/funding-oi-demo/status

# 런타임 로그
curl http://127.0.0.1:8000/api/trading/logs

# API/DB/OKX 연결 상태
curl http://127.0.0.1:8000/api/health
```

---

## 3) 현재 전략

현재 코드베이스에 남긴 실행 전략은 `Funding + OI Flush Reversal` 데모 트레이더입니다.
RSI/Bollinger/MACD류 Legacy 캔들 전략, 전략 자동 등록, 백테스트/최적화/검증 화면은 제거되었습니다.

---

## 4) 운영 팁

- Funding/OI 데모 트레이더는 별도 실행 프로세스로 운용합니다.
- 설정 화면은 실행 상태, 감시 종목, 오픈 포지션, 주문/청산 오류 수를 보여줍니다.
- 로그는 `/api/trading/logs`에서 확인 가능하며 DB 영구 저장을 우선 사용합니다.

---

## 5) 데스크탑 앱(Tauri)

```bash
cd desktop
npm install
npm run tauri:dev
```

자세한 내용은 `desktop/README.md` 참고.
