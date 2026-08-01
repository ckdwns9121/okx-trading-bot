# 트레이딩 봇 기능 지형도 리서치 (2026-08)

> 오픈소스 인기 봇 기능 전수 조사 + 기관 트레이딩 시스템 구조 조사 요약.
> 목적: OKX 봇에 어떤 기능이 표준으로 필요한지 판단 근거.

---

## Part 1. 오픈소스 트레이딩 봇 조사

### 주요 프로젝트 (2026-08 기준, 스타 수 근사치)

| 프로젝트 | Stars | 상태 | 콘셉트 |
|---|---|---|---|
| Freqtrade | ~50k | 활발 | 리테일 크립토 봇 프레임워크의 사실상 표준 (Python) |
| CCXT | ~43k | 활발 | 봇이 아닌 100+ 거래소 통합 API 라이브러리 (대부분의 봇이 이 위에 구축) |
| NautilusTrader | ~25k | 활발 | 기관급 이벤트드리븐 엔진, 백테스트=라이브 동일 코드, Rust 코어 |
| backtrader | ~23k | 유지보수 종료 | 1세대 백테스트 프레임워크 (신규 프로젝트 비추천) |
| QuantConnect LEAN | ~21k | 활발 | 멀티에셋 이벤트드리븐 엔진, Alpha/Portfolio/Execution/Risk 모듈 분리 |
| Hummingbot | ~19k | 활발 | 마켓메이킹/차익거래 특화, 140+ 자체 커넥터, Kill Switch |
| vectorbt | ~8.5k | 활발 | NumPy 벡터라이즈 초고속 백테스트 + walk-forward (리서치 도구) |
| Jesse | ~8.3k | 활발 | look-ahead bias 차단 백테스트 + Monte Carlo + Optuna 최적화 |
| OctoBot | ~6.3k | 활발 | 노코드 UI 중심, Grid/DCA/TradingView/LLM 모드 |
| Superalgos | ~5.6k | 느림 | 비주얼 노코드 전략 설계 |
| Gekko / Zenbot | 10k/8.3k | 아카이브 | 1세대 Node.js 봇 (2020/2022 종료) |
| TradingAgents / ai-hedge-fund / nofx | 80k/60k/13k | 급성장 | LLM 에이전트 계열. nofx는 실거래: "LLM이 결정 + Go 런타임이 리스크 하드 강제" 구조 |

### 전 프로젝트 공통 = 표준 기능 세트 (중요도 순)

1. **백테스트 → 페이퍼(dry-run) → 라이브 단일 파이프라인** — 동일 전략 코드가 세 모드에서 그대로 돎. 검증 안 된 전략으로 실돈을 잃는 걸 막는 3단 안전장치.
2. **거래소 커넥터 추상화** — 전략 코드와 거래소 API 분리, rate limit/서명/재시도 포함.
3. **리스크 관리 & 킬스위치** — 거래소측 stoploss, trailing stop, 일일 손실 한도, 최대 낙폭 서킷브레이커 (Freqtrade Protections: StoplossGuard/MaxDrawdown/Cooldown, Hummingbot Kill Switch).
4. **플러그인형 전략 프레임워크** — 베이스 클래스 상속 + 자동 발견 registry.
5. **히스토리 데이터 관리** — 다운로드 CLI + 로컬 저장 (SQLite/PostgreSQL/Parquet).
6. **파라미터 최적화 + 강건성 검증** — hyperopt/Optuna/유전알고리즘. 2026년 차별화 포인트는 과최적화 방어: walk-forward, Monte Carlo, lookahead 분석기.
7. **원격 모니터링/제어** — 웹 대시보드 + Telegram 제어(상태 확인·긴급 정지)가 리테일 표준 조합.
8. **알림** — Telegram/Discord/Webhook (체결·에러·서킷브레이커 발동 즉시 통지).
9. **Docker 배포** — 24/7 무인 운행 재현성.
10. **(차별화) ML/AI** — FreqAI(슬라이딩 윈도우 자동 재학습), OctoBot LLM 모드, nofx. 트렌드: "AI가 시그널, 결정론적 코드가 집행·리스크".

### Freqtrade 상세 (참조 표준)

- 전략: IStrategy 상속, pandas 기반, custom stoploss/DCA 콜백, pairlist 필터 플러그인
- 백테스트: 수수료·펀딩 반영, lookahead-bias 분석기 내장
- 최적화: Hyperopt (베이지안)
- Protections: 연속 손절 시 중지, equity 낙폭 초과 시 중지, 쿨다운
- FreqUI 웹 대시보드 + Telegram 완전 제어 + REST API
- FreqAI: LightGBM/XGBoost/PyTorch/RL 자동 재학습

---

## Part 2. 기관 트레이딩 시스템 구조

### 표준 스택 구성요소

- **Data pipeline**: 틱 저장소(kdb+/q, Man Group ArcticDB), point-in-time 데이터로 look-ahead/survivorship bias 차단 (survivor-only 백테스트는 연수익 ~4.9%p 과대평가 연구 존재)
- **Alpha research**: 노트북 + factor library + feature store. Two Sigma는 일 48,000+ 시뮬레이션
- **백테스트**: event-driven simulation (market event→signal→order→fill), 현실적 fill 모델, square-root impact 등 비용 모델
- **OMS vs EMS**: OMS=주문의 비즈니스 수명주기(승인·컴플라이언스·배분), EMS=체결 방법(라우팅·실행 알고). 흐름: OMS→FIX→EMS→거래소
- **실행 알고**: TWAP/VWAP/POV/Iceberg/SOR — 큰 주문의 market impact 최소화가 목적
- **Pre-trade risk**: 주문 발사 전 동기 차단 — fat-finger 한도, 가격 밴드, 포지션 한도. 미국 SEC Rule 15c3-5로 법적 강제. Knight Capital(2012): 배포 실수 + 자동 안전장치 부재로 45분간 $440M 손실
- **Post-trade**: TCA(implementation shortfall 측정), reconciliation(장부 vs 거래소 대사, drop copy), PnL attribution(알파/비용/펀딩 분해)
- **모니터링**: 대시보드 + 알림 + on-call, 데이터 품질 감시 포함
- **크립토 기관**: Talos(OEMS, Coin Metrics 인수), Wintermute(co-location, 실시간 인벤토리 리스크), 자산 90-95% 콜드 커스터디 + 거래분만 거래소

### 전략 수명주기 (승격 게이트)

```
Research → Backtest 게이트(OOS 최소 100-200 트레이드) → Paper/Incubation(파이프라인 전체 검증)
→ 소액 라이브(체결 품질 실측) → 점진 증액 → 상시 decay 모니터링
```

- WorldQuant "Alpha Factory": out-of-sample 통과한 알파만 자본 배분
- Decay 감지 핵심: **시그널 알파 감쇠 vs 실행 비용 악화를 TCA로 구분** — 혼동하면 멀쩡한 전략을 은퇴시키거나 죽은 전략을 방치

### 리테일이 베낄 것 (우선순위)

1. **Pre-trade risk gate** — 모든 주문이 통과하는 단일 함수: 최대 주문 크기, 가격 sanity check, 포지션·일일손실 한도, 주문 빈도 상한 + 자동 kill switch
2. **Reconciliation 루프** — 주기적으로 거래소 포지션/잔고 vs 내부 DB 대조, 불일치 시 알림/정지
3. **전 주문 TCA 기록** — 시그널 시점 가격 vs 실제 체결가 저장, implementation shortfall 누적 집계
4. **백테스트 정직성** — 비용 모델 필수, look-ahead 점검, 봉인된 out-of-sample, 상폐 코인 포함
5. **승격 게이트 프로세스** — research→backtest→paper N주→소액→정규, 단계별 통과 기준 문서화, 이탈 시 자동 강등
6. **알림 기반 모니터링** — heartbeat, 피드 gap, 주문 거부율, 일중 PnL
7. **주문 분할** (호가창 대비 큰 주문일 때만)
8. **거래소 counterparty 최소화** — 필요분만 예치, API 키 출금 권한 제거

베끼지 말 것: co-location/FPGA 저지연 경쟁, 정식 OMS/EMS 분리, 풀 VWAP/POV/SOR, 규제급 감사 인프라.

---

## 우리 봇 기준 갭 분석

현재 저장소는 전략을 걷어낸 상태(데이터 수집 + API + 대시보드 골격만 유지). 표준 세트 대비 앞으로 필요한 것 순서:

1. dry-run과 live의 코드 경로 통일 + 거래소측 stoploss + 다층 Protections (연속 손절 중지, 낙폭 서킷브레이커)
2. pre-trade risk gate + reconciliation + TCA 기록 (기관 파트 1~3순위)
3. 백테스트 강건성 도구 (walk-forward, Monte Carlo, lookahead 검증)
4. Telegram 알림/제어 (notifier 모듈은 이미 있음 — 제어 기능 확장)
5. 데이터 다운로드 CLI + Parquet 저장 표준화
