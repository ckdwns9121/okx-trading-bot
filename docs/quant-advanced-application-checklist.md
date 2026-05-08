# Quant Advanced 적용 체크리스트

작성일: 2026-05-08

대상 문서: `docs/quant-advanced/01` ~ `09` 9개 문서.  
목표: 고급 이론을 바로 덧붙이는 것이 아니라, 현재 OKX 봇의 백테스트 신뢰도, 리스크 생존성, 체결 현실성, 신호 품질 분석을 단계적으로 강화한다.

## 현재 봇 기준 핵심 결론

- 최우선은 새 전략 추가가 아니라 **검증 품질 개선**이다.
- `example_rsi`처럼 PnL이 큰 전략도 Max DD가 너무 크면 후보에서 제외해야 한다.
- `rsi_bollinger_combo`는 공격적 연구 후보, `rsi_bollinger_regime` limited 계열은 안전성 우선 demo 후보로 두고 아래 체크리스트를 적용한다.
- 강화학습, 확률미적분, HFT 전체 구현은 뒤로 미룬다. 지금은 Monte Carlo, microstructure, volatility filter, purged walk-forward, signal labeling이 더 실용적이다.

## 이미 있는 기반

- [x] 전략 registry와 여러 전략 모듈
- [x] 백테스트 엔진
- [x] 수수료, 슬리피지, 펀딩비, liquidity impact 일부 반영
- [x] backtest sensitivity API 일부
- [x] Monte Carlo 함수와 `/api/backtest/{run_id}/monte-carlo`
- [x] circuit breaker: daily/monthly/total drawdown 차단
- [x] ATR, Bollinger Band, regime detector 일부
- [x] demo 전용 `rsi_bollinger_regime` limited profile/runbook
- [x] 전체 전략 비교 Markdown 리포트 생성 스크립트

## P0: 먼저 해야 할 것

### 1. 백테스트 리포트에 Monte Carlo를 붙인다

- [ ] 전체 전략 비교 리포트에 Monte Carlo 요약 컬럼 추가
- [ ] 전략별 `p95_max_drawdown`, `ruin_probability`, `p5_final_balance` 계산
- [ ] PnL 순위와 별도로 `survival_rank` 추가
- [ ] `ruin_probability > 1%` 또는 `p95_max_drawdown > 40%`이면 자동으로 `실거래 금지` 판정
- [ ] 포지션 사이즈 5%, 10%, 25%, 100%별 Monte Carlo 비교
- [ ] `rsi_bollinger_combo`와 `rsi_bollinger_regime limited`를 먼저 대상으로 검증

완료 기준:

- [ ] Markdown 리포트에 “수익 순위”와 “생존성 순위”가 분리되어 있다.
- [ ] Max DD가 낮은 전략이 총 PnL만 높은 전략보다 우선될 수 있다.

### 2. Walk-forward 검증을 표준 게이트로 만든다

- [ ] 모든 추천 전략은 단일 기간 백테스트가 아니라 train/validation/holdout 또는 rolling window로 검증
- [ ] `2024_Q1`, `2024_Q3`, `2025_Q1`, `2025_Q3`, `2026_Q1` 같은 고정 구간 재사용
- [ ] 구간별 PnL, PF, Sharpe, Max DD, trade_count 저장
- [ ] 중앙 PnL이 음수인 전략은 총 PnL이 높아도 탈락
- [ ] 양수 실행 비율, 최악 구간 손실, Max DD 기준을 리포트에 명시

완료 기준:

- [ ] “추천 전략”은 반드시 walk-forward 결과 파일을 근거로 한다.
- [ ] 단일 90일 리포트만으로는 demo/live 승격하지 않는다.

### 3. Market microstructure 필터를 최소 구현한다

- [ ] OKX best bid/ask 또는 ticker 기반 spread 조회 함수 추가
- [ ] `max_spread_pct` 설정 추가
- [ ] 신규 진입 전 `spread_pct > max_spread_pct`이면 진입 차단
- [ ] order book top depth 조회 함수 추가
- [ ] 주문 notional 대비 top depth가 부족하면 진입 차단
- [ ] 실전 fill price와 expected price 차이를 trade/runtime event에 저장
- [ ] 백테스트 동적 슬리피지 모델을 `spread/2 + impact_factor * order_size / visible_liquidity` 구조로 확장

완료 기준:

- [ ] 실거래/demo 진입 전에 spread/depth 로그가 남는다.
- [ ] “신호는 좋았지만 체결 환경이 나빠서 진입 차단”된 케이스를 리포트할 수 있다.

### 4. Volatility regime 필터를 추천 전략에 적용한다

- [ ] `rsi_bollinger_combo`에 volatility filter profile 추가
- [ ] `bb_width_pct`, `bb_width_percentile`, `ATR/price` 계산
- [ ] 변동성이 너무 낮은 구간의 가짜 돌파 차단
- [ ] 변동성이 과도한 구간의 추격 진입 차단
- [ ] volatility regime별 전략 성과 리포트 추가
- [ ] ATR 기반 position sizing을 백테스트와 demo 양쪽에 일관되게 반영

완료 기준:

- [ ] 전체 성과뿐 아니라 low/normal/high volatility regime별 성과가 나온다.
- [ ] Max DD 개선 여부가 PnL 감소와 함께 비교된다.

## P1: 신호 품질 분석과 ML 전 단계

### 5. 신호별 feature/outcome 저장

- [ ] `strategy_signals` 모델/마이그레이션 설계
- [ ] 후보 신호마다 timestamp, pair, timeframe, strategy_name, signal_side 저장
- [ ] feature 저장: `ma_distance_pct`, `ma_slope_pct`, `bb_width_pct`, `bb_room_pct`, `atr_pct`, `volume_ratio`, `funding_rate`, `spread_pct`, `regime_label`
- [ ] outcome 저장: `outcome_pnl`, `bars_to_exit`, `exit_reason`, `max_adverse_excursion`, `max_favorable_excursion`
- [ ] 백테스트와 demo/live에서 같은 schema를 사용

완료 기준:

- [ ] “어떤 조건의 신호가 손실을 냈는지” SQL/리포트로 확인할 수 있다.

### 6. Triple barrier labeling

- [ ] 각 후보 신호에 TP/SL/time barrier 정의
- [ ] ATR 기반 barrier와 Bollinger Band barrier를 모두 실험
- [ ] label: `win`, `loss`, `timeout` 또는 `1/0/-1` 정의
- [ ] label 생성 스크립트 추가
- [ ] label별 feature 분포 리포트 생성

완료 기준:

- [ ] 단순 “N봉 뒤 상승/하락”이 아니라 실제 청산 조건 기반 label이 생성된다.

### 7. Meta-labeling 실험

- [ ] primary model은 기존 룰 전략으로 유지
- [ ] ML은 “진입할지 말지”만 판단
- [ ] logistic regression 또는 random forest부터 시작
- [ ] random train/test split 금지
- [ ] purged walk-forward validation 적용
- [ ] accuracy 대신 precision, expected value, drawdown, turnover, out-of-sample PnL로 평가
- [ ] 확률 threshold별 trade_count/PnL/DD 변화 리포트

완료 기준:

- [ ] ML이 직접 매수/매도하지 않는다.
- [ ] 나쁜 신호를 줄여 Max DD 또는 profit factor가 개선되는지 검증된다.

### 8. 확률 기반 bet sizing

- [ ] meta-model 성공 확률을 position size로 변환하는 함수 추가
- [ ] 확률 50~55%: 최소 size, 55~65%: 중간 size, 65% 이상: 상한 size 같은 conservative ladder부터 시작
- [ ] Kelly full sizing 금지, fractional/capped sizing만 허용
- [ ] Monte Carlo로 size ladder별 ruin probability 확인

완료 기준:

- [ ] size를 키운 결과가 아니라, ruin probability가 허용 범위 안에 있는지가 승격 기준이 된다.

## P2: 전략 다변화

### 9. Statistical arbitrage를 별도 전략군으로 분리

- [ ] BTC/ETH, BTC/SOL, ETH/SOL 가격비율 데이터셋 생성
- [ ] rolling correlation stability 리포트
- [ ] z-score mean reversion baseline
- [ ] half-life 계산
- [ ] ADF/Johansen cointegration test 추가
- [ ] 양방향 동시 체결 실패 리스크 정의
- [ ] pair별 손절/익절/timeout 설정
- [ ] 단일 방향 전략과 별도 리스크 한도 적용

완료 기준:

- [ ] 기존 단일 instrument 전략과 섞지 않고 별도 리포트와 별도 리스크 정책으로 평가한다.

## P3: 장기 연구로 미룰 것

### 10. Reinforcement learning

- [ ] 바로 매수/매도 정책 학습 금지
- [ ] 먼저 신호 feature 저장, triple barrier, meta-labeling, Monte Carlo를 완료
- [ ] 이후에만 sizing 또는 exit timing 보조 역할로 실험
- [ ] 실전 연결 금지, research sandbox 전용

### 11. Stochastic calculus

- [ ] 옵션/변동성 상품을 다루기 전까지 직접 구현하지 않음
- [ ] 단기적으로는 GBM 기반 liquidation probability 또는 price path stress test 정도만 검토
- [ ] 정규분포/연속가격 가정이 깨지는 crypto tail risk를 항상 명시

### 12. HFT architecture

- [ ] HFT 전략 구현은 보류
- [ ] 개념만 가져와서 WebSocket, latency log, order ack tracking, kill switch 강화에 적용
- [ ] full depth/tick 저장은 저장 비용과 API 제한을 검토한 뒤 진행

## 추천 적용 순서

1. `rsi_bollinger_combo`와 `rsi_bollinger_regime limited`에 Monte Carlo 생존성 리포트 붙이기
2. 전체 전략 비교 리포트에 walk-forward/Monte Carlo gate 추가
3. spread/depth 진입 필터 구현
4. volatility regime별 성과 리포트 생성
5. `rsi_bollinger_combo` risk-limited/volatility-filtered profile 설계
6. signal feature 저장 테이블 추가
7. triple barrier label 생성
8. meta-labeling으로 나쁜 신호 필터링
9. capped probability sizing 실험
10. statistical arbitrage 별도 전략군 착수

## 전략 승격 게이트

- [ ] 단일 기간이 아니라 walk-forward 통과
- [ ] Monte Carlo `ruin_probability <= 1%`
- [ ] Monte Carlo `p95_max_drawdown <= 40%`
- [ ] 최악 구간 손실이 계좌 중단 기준 안에 있음
- [ ] 수수료/슬리피지/펀딩비/동적 슬리피지 반영 후에도 양수
- [ ] spread/depth 필터 적용 후 trade_count가 충분함
- [ ] demo 4주 관찰에서 주문 실패, stale position, 과도한 pause가 없음
- [ ] live 전환 전 position size 상한과 daily/monthly/total loss limit이 명시됨

## 피해야 할 것

- [ ] 총 PnL만 보고 전략 추천
- [ ] Max DD 50% 이상 전략을 “수익 전략”으로 포장
- [ ] 전체 기간 최적화 후 같은 기간 성과 보고
- [ ] random train/test split 사용
- [ ] 수수료/슬리피지/펀딩비 무시
- [ ] 신호 수가 부족한데 복잡한 ML 모델 사용
- [ ] RL에게 바로 매수/매도 맡기기
- [ ] HFT 수준 인프라 없이 초단타 전략 착수
