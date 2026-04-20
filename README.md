# OKX Trading Bot (Demo/Live) + Dashboard + Desktop

OKX 선물(스왑) 자동매매를 위한 통합 프로젝트입니다.

- **Bot API (FastAPI)**: 전략 실행, 백테스트, 포지션/거래/로그 관리
- **Web Dashboard (Next.js)**: 실시간 상태, 설정, 백테스트/검증 UI
- **Desktop App (Tauri + React + TS)**: 데스크탑 환경에서 동일 기능 사용
- **DB (PostgreSQL)**: 거래, 백테스트, 런타임 이벤트 로그 영구 저장

> ⚠️ 투자 손실 위험이 있습니다. 본 프로젝트는 학습/실험 목적이며 투자 조언이 아닙니다.

---

## 1) 프로젝트 구조

```text
.
├─ bot/           # FastAPI + 전략 엔진 + 백테스트 + OKX 연동
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

### 2-3. 자주 쓰는 API
### 2-4. Analysis Skill (v1)

```bash
# 분석 Skill(v1) 실행
curl -X POST http://127.0.0.1:8000/api/analysis/skill/run \
  -H 'Content-Type: application/json' \
  -d '{"strategy_name":"example_rsi","baseline_strategy_name":"example_rsi","pair":"ETH-USDT-SWAP","timeframe":"1H","windows":[{"name":"train","start":"2026-03-01T00:00:00","end":"2026-03-05T00:00:00"},{"name":"val","start":"2026-03-05T00:00:00","end":"2026-03-08T00:00:00"},{"name":"holdout","start":"2026-03-08T00:00:00","end":"2026-03-10T00:00:00"}],"assumptions":{"initial_balance":10000,"leverage":3,"fee_rate":0.0005,"slippage_pct":0.05,"funding_rate_per_8h":0.0001,"cooldown_candles":1,"liquidity_impact_factor":0.1,"maintenance_margin_ratio":0.005,"liquidation_fee_pct":0.002},"search_space":{"rsi_period":[7,21],"oversold":[20,40],"overbought":[60,80]},"top_k":3,"run_limits":{"max_combinations":100,"timeout_sec":900,"retry_per_failed_job":1,"partial_failure_threshold":0.2}}'
```

자세한 계약/정책/Replay 규칙은 `docs/trading-analysis-skill-v1.md`를 참고하세요.


```bash
# 엔진 시작/정지
curl -X POST http://127.0.0.1:8000/api/trading/start
curl -X POST http://127.0.0.1:8000/api/trading/stop

# 현재 엔진 상태
curl http://127.0.0.1:8000/api/trading/status

# 사용 가능한 전략 목록
curl http://127.0.0.1:8000/api/config/strategies

# 전략 설정 목록
curl http://127.0.0.1:8000/api/config
```

---

## 3) 전략 목록 (전체)

아래는 현재 레지스트리에 자동 등록되는 전략 전부입니다.

### 3-1. `bollinger_band`
- 유형: 볼린저밴드 평균회귀
- 진입: 하단 밴드 이탈 시 Long / 상단 밴드 이탈 시 Short
- 청산: 중단선(SMA) 복귀
- 주요 파라미터: `period(20)`, `std_dev(2.0)`

### 3-2. `breakout_strategy`
- 유형: 돈치안 채널 돌파
- 진입: N기간 고점 돌파 Long / 저점 이탈 Short
- 청산: 채널 중간값 복귀
- 주요 파라미터: `channel_period(20)`

### 3-3. `chronos_regime_hybrid`
- 유형: **Chronos-2 예측 + 레짐필터 + 폴백 복합 전략**
- 진입: 예측 중앙값(q50) 기반 기대수익률(edge)이 임계치 이상일 때 방향 진입
- 필터: 레짐(trending_up/down)과 신뢰도(confidence)로 역추세 진입 차단
- 청산: edge 약화, 반대 레짐 전환 등
- 폴백: Chronos 불가 시 `rsi_bollinger_regime`
- 주요 파라미터:
  - `prediction_length`, `min_context`, `entry_edge_pct`, `exit_edge_pct`
  - `max_uncertainty_pct`, `regime_confidence_min`
  - `base_size_pct`, `min_size_pct`, `fallback_enabled`
- 참고 문서: `docs/chronos-hybrid-strategy.md`

### 3-4. `elliott_wave_fib`
- 유형: 엘리어트 파동 + 피보나치 + RSI + 거래량 합성
- 진입: 파동 위치 + 피보나치 근접 + RSI 확인 + 거래량 확인 **동시 충족**
- 특징: 신호 수는 적지만 엄격한 조건 필터
- 주요 파라미터: `swing_threshold`, `fib_entry_tolerance`, `rsi_period`, `volume_period`, `stop_loss_pct`

### 3-5. `example_rsi`
- 유형: RSI 평균회귀
- 진입: RSI 과매도/과매수
- 청산: RSI 중립(50선) 복귀
- 주요 파라미터: `rsi_period`, `oversold`, `overbought`, `atr_period`, `tp_atr_mult`, `sl_atr_mult`, `trailing_stop_pct`

### 3-6. `example_sma_cross`
- 유형: SMA 골든/데드크로스 추세추종
- 진입: fast SMA 상향돌파 Long / 하향돌파 Short
- 주요 파라미터: `fast_period(10)`, `slow_period(30)`

### 3-7. `livermore`
- 유형: 리버모어식 피벗 돌파 + 피라미딩 + 트레일링 스탑
- 진입: 피벗 돌파 + 거래량 확인 + 추세 확인
- 청산: 트레일링 스탑, 추세 반전
- 특징: 수익 구간 추가진입(피라미딩)
- 주요 파라미터: `pivot_period`, `volume_factor`, `trend_ema_period`, `max_pyramids`, `initial_stop_pct`, `trail_step_pct`

### 3-8. `macd_strategy`
- 유형: MACD 추세추종
- 진입: MACD/Signal 골든크로스 Long, 데드크로스 Short
- 청산: 반대 크로스
- 주요 파라미터: `fast_period(12)`, `slow_period(26)`, `signal_period(9)`

### 3-9. `mean_reversion`
- 유형: Z-Score 평균회귀
- 진입: Z-score 임계치 초과(±entry_z)
- 청산: 중립영역(±exit_z) 복귀
- 주요 파라미터: `period(30)`, `entry_z(2.0)`, `exit_z(0.5)`

### 3-10. `multi_ema`
- 유형: 다중 EMA 기반 레짐 + 눌림목/반등 진입
- 진입: EMA 정렬(상승/하락) 확정 후 pullback 조건 충족
- 청산: 레짐 변경
- 주요 파라미터: `fast(8)`, `medium(21)`, `slow(55)`, `pullback_pct(0.3)`

### 3-11. `multi_factor`
- 유형: 다요인 점수화 합성 전략
- 요인: 모멘텀, 추세강도(ADX), RSI, 거래량 이상치, 변동성(ATR), 볼린저 위치
- 진입/청산: 가중합 점수가 임계치 상/하 돌파 시 진입, 중립 복귀 시 청산
- 주요 파라미터:
  - 기간: `momentum_period`, `adx_period`, `rsi_period`, `volume_period`, `bb_period`, `bb_std`
  - 가중치: `w_momentum`, `w_trend`, `w_rsi`, `w_volume`, `w_volatility`, `w_position`
  - 임계치: `entry_threshold`, `exit_threshold`

### 3-12. `rsi_bollinger_combo`
- 유형: RSI + 볼린저 듀얼 확인
- 진입: RSI 조건 + 밴드 이탈 조건 **동시 충족**
- 청산: RSI 중립영역 복귀
- 주요 파라미터: `rsi_period(14)`, `rsi_oversold(35)`, `rsi_overbought(65)`, `bb_period(20)`, `bb_std(2.0)`

### 3-13. `rsi_bollinger_regime`
- 유형: RSI+볼린저 + ADX/EMA 레짐 필터
- 진입: `rsi_bollinger_combo` 진입 조건 + 레짐 방향 필터
- 특징: 강한 상승/하락장에서 역방향 진입 억제
- 주요 파라미터:
  - `rsi_period`, `rsi_oversold`, `rsi_overbought`, `bb_period`, `bb_std`
  - `adx_period`, `adx_threshold`, `ema_fast_period`, `ema_slow_period`

### 3-14. `volume_momentum`
- 유형: 거래량 가중 모멘텀
- 진입: VWAP 방향 + 거래량 비율 + 모멘텀 3중 확인
- 청산: 거래량 둔화 또는 VWAP 재교차
- 주요 파라미터: `period(14)`, `volume_threshold(1.5)`, `momentum_threshold(2.0)`

---

## 4) 운영 팁

- 전략은 **페어 단위**로 활성/비활성됩니다.
- `is_active=true` 전략만 라이브 엔진에서 실행됩니다.
- 실행 중 전략 변경 후에는 `start/stop` 또는 재시작으로 반영 상태를 확인하세요.
- 로그는 `/api/trading/logs`에서 확인 가능하며 DB 영구 저장을 우선 사용합니다.

---

## 5) 데스크탑 앱(Tauri)

```bash
cd desktop
npm install
npm run tauri:dev
```

자세한 내용은 `desktop/README.md` 참고.
