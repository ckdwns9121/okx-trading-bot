# OKX Trading Bot (Demo) + Dashboard + Desktop

OKX 자동매매 실험 프로젝트입니다. **리스크 안전장치 우선** 원칙으로 재구축되었으며,
현재는 검증 단계(페이퍼/데모 트레이딩)만 실행합니다. 실거래 실행기는 의도적으로 없습니다.

- **Bot API (FastAPI)**: 리스크 게이트/킬스위치, 장부 대사, 체결 품질(TCA), 페이퍼 상태, 런타임 로그
- **Web Dashboard (Next.js)**: 킬스위치 긴급 정지, 리스크 한도, 실시간 로그, 마켓/거래 내역
- **Desktop App (Tauri + React + TS)**: 데스크탑 환경에서 동일 기능 사용
- **DB (PostgreSQL)**: 거래, 런타임 이벤트 로그, 연구용 시장 스냅샷 영구 저장

> ⚠️ 투자 손실 위험이 있습니다. 본 프로젝트는 학습/실험 목적이며 투자 조언이 아닙니다.

---

## 1) 프로젝트 구조

```text
.
├─ bot/           # FastAPI + 안전장치(risk gate/reconciliation/TCA) + 전략/트레이더 + OKX 연동
├─ dashboard/     # Next.js 웹 대시보드
├─ desktop/       # Tauri 데스크탑 앱
├─ docs/          # 리서치/운영 문서
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
- `OKX_MODE=demo` (데모계좌 — 데모 트레이더는 demo 모드가 아니면 실행을 거부합니다)
- `DATABASE_URL`
- 리스크 한도: `RISK_MAX_ORDER_NOTIONAL_USD`, `RISK_MAX_TOTAL_EXPOSURE_USD`,
  `MAX_DAILY_LOSS_USD`, `RISK_MAX_ORDERS_PER_MINUTE` 등 (`.env.example` 참고)
- (선택) 텔레그램 알림: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

### 2-2. 전체 스택 실행

```bash
docker compose up -d --build
```

접속:

- Dashboard: http://127.0.0.1:3000
- Bot API: http://127.0.0.1:8000
- OpenAPI: http://127.0.0.1:8000/docs

---

## 3) 안전장치 (모든 주문의 전제 조건)

모든 트레이더(페이퍼/데모)는 주문 전에 반드시 아래를 통과합니다.

| 장치 | 내용 |
|---|---|
| Pre-trade Risk Gate | 주문당 금액·종목/총 노출 한도·가격 괴리·분당 주문 수 검사 |
| Kill Switch | 일일 손실 한도 초과 또는 장부 불일치 시 자동 발동, 파일로 영속화(재시작에도 유지), 수동 발동/해제 가능 |
| Reconciliation | 봇 내부 장부 vs OKX 실제 포지션 주기 대조, 불일치 시 킬스위치 |
| TCA (체결 품질) | 주문마다 판단가 vs 체결가 기록 → 전략 문제와 체결 문제를 구분 |

```bash
# 리스크 상태 / 킬스위치
curl http://127.0.0.1:8000/api/risk/status
curl -X POST http://127.0.0.1:8000/api/risk/kill-switch/trip -H 'Content-Type: application/json' -d '{"reason":"manual stop"}'
curl -X POST http://127.0.0.1:8000/api/risk/kill-switch/reset

# 장부 대사 / 체결 품질 요약
curl "http://127.0.0.1:8000/api/risk/reconciliation"
curl http://127.0.0.1:8000/api/risk/execution-quality
```

대시보드 설정 페이지에서도 킬스위치 상태 확인과 긴급 정지가 가능합니다.

---

## 4) 현재 전략: Daily MA Trend Following (BTC/ETH)

20/50/100일 이동평균 앙상블 기반 추세추종, 롱/플랫 전용(숏 없음).
종가가 3개 MA 중 몇 개 위에 있는지로 목표 비중(0/33/67/100%)을 정합니다.

전략 수명주기(승격 게이트): `백테스트 → 페이퍼/데모 → 소액 실거래 → 증액`.
각 단계는 이전 단계 통과 근거가 있어야 넘어갑니다.

### 4-1. 백테스트 (실데이터, 수수료 반영, 룩어헤드 차단)

```bash
docker compose exec bot python -m scripts.run_trend_following_paper_trader --backtest --backtest-days 900
```

### 4-2. 내장 페이퍼 트레이딩 (주문 전송 없음, 현물 시뮬레이션)

```bash
docker compose exec -d bot python -m scripts.run_trend_following_paper_trader
curl http://127.0.0.1:8000/api/paper/trend-following   # 가상 장부 조회
```

### 4-3. OKX 데모 트레이딩 (데모 계좌에 실제 주문, 무기한 1x)

```bash
# 1회 평가 (스모크 테스트)
docker compose exec bot python -m scripts.run_trend_following_demo_trader --once

# 상시 루프 (매시간 체크, 새 일봉 확정 시에만 판단)
docker compose exec -d bot python -m scripts.run_trend_following_demo_trader
```

- 계정 포지션 모드(net / long·short)를 자동 감지합니다.
- `OKX_MODE=demo`가 아니면 실행을 거부합니다.

### 4-4. 관찰

```bash
curl http://127.0.0.1:8000/api/trading/logs    # 신호/체결/오류 이벤트
curl http://127.0.0.1:8000/api/health          # API/DB/OKX 연결 상태
```

---

## 5) 시장 데이터 수집 (리서치용)

```bash
cd bot
.venv/bin/python scripts/collect_crowded_perp_snapshots.py --dry-run --duration 30 --interval 10
.venv/bin/python scripts/collect_basis_arbitrage_snapshots.py --dry-run --duration 30 --interval 10
```

전략 리서치 배경은 `docs/research/trading-bot-feature-landscape-2026.md` 참고
(오픈소스 봇 기능 조사 + 기관 시스템 구조 + 이 프로젝트의 갭 분석).

---

## 6) 테스트

```bash
cd bot && .venv/bin/python -m pytest         # 백엔드 (전략/안전장치/API)
cd dashboard && npm run build                 # 대시보드
```

---

## 7) 데스크탑 앱(Tauri)

```bash
cd desktop
npm install
npm run tauri:dev
```

자세한 내용은 `desktop/README.md` 참고.
