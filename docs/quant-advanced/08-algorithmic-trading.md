# Algorithmic Trading — 알고리즘 트레이딩

## 1. 한 줄 요약

**Algorithmic Trading(알고리즘 트레이딩)**은 사람이 직접 매수/매도 버튼을 누르는 대신, 미리 정의한 규칙이나 모델에 따라 자동으로 거래하는 방식입니다.

현재 OKX 트레이딩 봇은 이 범주에 속합니다.

## 2. 알고리즘 트레이딩의 범위

알고리즘 트레이딩은 매우 넓은 개념입니다.

포함되는 것:

- 이동평균선 전략
- RSI 전략
- 볼린저밴드 전략
- 추세추종
- 평균회귀
- 페어트레이딩
- 머신러닝 전략
- 마켓메이킹
- HFT
- 포트폴리오 리밸런싱

즉 단순 룰 전략부터 고급 머신러닝까지 모두 algorithmic trading입니다.

## 3. 기본 구성요소

### 3.1 Data

전략이 사용할 데이터입니다.

- OHLCV 캔들
- tick data
- order book
- funding rate
- open interest
- volatility
- macro data
- sentiment data

### 3.2 Signal Generation

매수/매도 후보를 만드는 부분입니다.

예:

```text
5분봉 종가가 7일 이동평균선 위로 돌파
다음 봉도 위에서 유지
볼린저밴드 필터 통과
```

### 3.3 Risk Management

전략보다 더 중요할 수 있습니다.

- 포지션 크기
- 손절
- 최대 일일 손실
- 최대 drawdown
- 연속 손실 제한
- 레버리지 제한

### 3.4 Execution

주문을 어떻게 넣을지 결정합니다.

- 시장가
- 지정가
- 분할 주문
- post-only
- reduce-only

### 3.5 Backtesting

과거 데이터에서 전략을 검증합니다.

### 3.6 Monitoring

실전 운용 중 전략 상태를 감시합니다.

- 포지션
- 주문
- PnL
- 오류
- API 연결
- latency

## 4. 전략 유형

### 4.1 Trend Following

추세가 이어진다는 가정입니다.

예:

- 이동평균 돌파
- Donchian breakout
- MACD
- ADX trend filter

### 4.2 Mean Reversion

가격이 평균으로 돌아온다는 가정입니다.

예:

- RSI 과매수/과매도
- Bollinger Band bounce
- z-score strategy

### 4.3 Breakout

중요 가격대를 돌파하면 강한 움직임이 나온다는 가정입니다.

### 4.4 Market Making

bid와 ask 양쪽에 주문을 두고 spread를 얻는 전략입니다.

### 4.5 Statistical Arbitrage

자산 간 관계의 괴리를 거래합니다.

### 4.6 Machine Learning Strategy

데이터에서 패턴을 학습해 신호를 생성하거나 필터링합니다.

## 5. 좋은 자동매매 시스템의 조건

좋은 전략 하나보다 좋은 시스템이 더 중요합니다.

필수 조건:

- 데이터 정합성
- 현실적인 백테스트
- 수수료/슬리피지 반영
- 리스크 제한
- 장애 복구
- 주문 중복 방지
- 로그와 리포트
- 전략별 성과 분석
- 운영 중단 스위치

## 6. 백테스트에서 조심할 점

### 6.1 Look-ahead Bias

미래 데이터를 보고 과거에 진입한 것처럼 계산하는 오류입니다.

### 6.2 Survivorship Bias

살아남은 종목만 보고 전략을 평가하는 오류입니다.

### 6.3 Overfitting

과거 데이터에 너무 맞춘 전략입니다.

### 6.4 Unrealistic Fill

실제로 체결 불가능한 가격으로 백테스트하는 오류입니다.

### 6.5 Ignoring Costs

수수료와 슬리피지를 무시하면 대부분 전략이 과대평가됩니다.

## 7. 현재 프로젝트 상태

현재 OKX 봇은 다음 기능을 갖고 있습니다.

- FastAPI backend
- 전략 registry
- 백테스트 엔진
- 여러 전략 모듈
- DB 기반 candle/trade 저장
- 리스크 관리 일부
- dashboard/desktop UI

현재 전략 수준은 주로 기술적 지표 기반입니다.

## 8. 앞으로 발전 방향

추천 순서:

1. 단일 전략의 신호별 성과 저장
2. 볼린저밴드/ATR/거래량 필터 최적화
3. walk-forward validation
4. Monte Carlo risk analysis
5. market microstructure 필터
6. meta-labeling
7. 포지션 사이징 고도화
8. 전략 포트폴리오 구성

## 9. 알고리즘 전략 설계 체크리스트

전략을 만들 때 다음 질문에 답해야 합니다.

```text
무슨 시장 비효율을 노리는가?
진입 조건은 무엇인가?
청산 조건은 무엇인가?
손절 조건은 무엇인가?
포지션 크기는 어떻게 정하는가?
어떤 시장 regime에서 작동하는가?
수수료 후에도 기대값이 양수인가?
최대 손실은 어느 정도인가?
과최적화 가능성은 없는가?
실전 체결 가능한가?
```

## 10. 이 프로젝트에서의 핵심 원칙

- 신호보다 리스크 관리가 먼저
- 백테스트보다 out-of-sample 검증이 중요
- 승률보다 손익비와 MDD가 중요
- 수익률보다 생존 가능성이 중요
- 복잡한 모델보다 검증 가능한 단순 모델이 우선

## 11. 요약

알고리즘 트레이딩은 자동화된 매매 전체를 의미합니다.

현재 봇은 이미 이 영역에 들어와 있으며, 다음 단계는 단순 지표 전략을 더 현실적인 리스크/검증/실행 시스템으로 발전시키는 것입니다.
