# 퀀트 트레이딩 고급 분야 학습 인덱스

이 디렉터리는 퀀트 트레이딩 고급 주제를 하나씩 분리해서 정리한 문서 모음입니다.
목표는 “이론을 아는 것”이 아니라, 현재 OKX 자동매매 봇에 어떤 순서로 안전하게 도입할 수 있는지 판단하는 것입니다.

## 전체 문서 목록

| 순서 | 문서 | 핵심 질문 | 현재 봇과의 관련도 |
|---:|---|---|---|
| 1 | [Algorithmic Trading](./08-algorithmic-trading.md) | 규칙 기반 자동매매를 어떻게 설계·검증할 것인가? | 매우 높음 |
| 2 | [Market Microstructure](./04-market-microstructure.md) | 슬리피지, 스프레드, 체결 실패를 어떻게 반영할 것인가? | 매우 높음 |
| 3 | [Advances in Financial Machine Learning](./09-advances-in-financial-machine-learning.md) | 과최적화와 데이터 누수를 어떻게 막을 것인가? | 매우 높음 |
| 4 | [Monte Carlo](./02-monte-carlo.md) | 전략이 운 좋게 좋아 보이는 것인지 어떻게 확인할 것인가? | 높음 |
| 5 | [Volatility Trading](./05-volatility-trading.md) | 방향보다 변동성 상태를 어떻게 이용할 것인가? | 높음 |
| 6 | [Statistical Arbitrage](./06-statistical-arbitrage.md) | 가격 괴리와 평균회귀를 어떻게 전략화할 것인가? | 중간 |
| 7 | [Reinforcement Learning](./03-reinforcement-learning.md) | AI가 매매 행동을 학습하게 만들 수 있는가? | 낮음, 장기 과제 |
| 8 | [Stochastic Calculus](./01-stochastic-calculus.md) | 가격과 변동성을 수학적 확률 과정으로 어떻게 모델링할 것인가? | 낮음, 옵션/리스크 중심 |
| 9 | [HFT Architecture](./07-hft-architecture.md) | 초저지연 매매 시스템은 어떻게 구성되는가? | 낮음, 인프라 장기 과제 |

## 추천 학습 순서

현재 봇이 이미 백테스팅, 전략 클래스, 리스크 파라미터, 수수료/슬리피지 모델을 가지고 있으므로 아래 순서가 가장 실전적입니다.

### 1단계: 지금 바로 필요한 기반

1. [Algorithmic Trading](./08-algorithmic-trading.md)
2. [Market Microstructure](./04-market-microstructure.md)
3. [Advances in Financial Machine Learning](./09-advances-in-financial-machine-learning.md)

이 단계의 목적은 전략을 많이 만드는 것이 아니라, 전략 평가가 거짓으로 좋아지는 문제를 줄이는 것입니다.

우선 도입할 것:

- 수수료, 슬리피지, 스프레드 반영
- 진입/청산 조건과 체결 조건 분리
- 백테스트 구간 분리
- walk-forward 검증
- purged cross-validation 개념 반영
- 과최적화 방지 리포트

### 2단계: 전략 안정성 검증

4. [Monte Carlo](./02-monte-carlo.md)
5. [Volatility Trading](./05-volatility-trading.md)

이 단계의 목적은 “수익률이 높냐”보다 “망할 가능성이 얼마나 되냐”를 보는 것입니다.

우선 도입할 것:

- 거래 순서 셔플 Monte Carlo
- 슬리피지 증가 시나리오
- 연속 손실 시나리오
- 파산 확률 추정
- 변동성 필터
- ATR/Bollinger Band 기반 regime 구분

### 3단계: 별도 전략군으로 확장

6. [Statistical Arbitrage](./06-statistical-arbitrage.md)

이 단계는 현재 추세추종/돌파 전략과 성격이 다릅니다.
BTC-ETH, BTC-SOL, ETH-SOL 같은 페어를 대상으로 별도 전략 엔진처럼 접근하는 것이 좋습니다.

우선 도입할 것:

- 가격비율 z-score
- 상관관계 필터
- 공적분 테스트
- 시장중립 포지션
- 페어별 손절/익절

### 4단계: 장기 연구 과제

7. [Reinforcement Learning](./03-reinforcement-learning.md)
8. [Stochastic Calculus](./01-stochastic-calculus.md)
9. [HFT Architecture](./07-hft-architecture.md)

이 단계는 당장 봇에 붙이기보다 연구용으로 분리하는 것이 안전합니다.

주의:

- 강화학습은 데이터 누수와 과최적화 위험이 매우 큼
- 확률미적분은 현물/선물 단기 전략보다 옵션·변동성 모델에 더 적합함
- HFT는 코드보다 인프라, 거래소 위치, 네트워크 지연이 핵심임

## 현재 OKX 봇에 추천하는 적용 우선순위

### 최우선

1. 백테스트 리포트에 Monte Carlo 결과 추가
2. 전략별 walk-forward 검증 추가
3. 슬리피지/수수료 민감도 분석 추가
4. Bollinger Band, ATR 기반 변동성 regime 필터 강화
5. 진입 신호와 실제 체결 가능성 분리

### 다음

6. triple barrier 라벨링 실험
7. meta-labeling으로 “진입해도 되는 신호”와 “버릴 신호” 분리
8. bet sizing으로 포지션 크기 동적 조정
9. 페어트레이딩 전략 추가

### 나중

10. 강화학습 환경 구성
11. 옵션/변동성 모델 연구
12. 초저지연 주문 처리 구조 검토

## 실전 도입 로드맵

| 단계 | 할 일 | 기대 효과 |
|---:|---|---|
| 1 | 기존 전략 백테스트에 수수료·슬리피지·스프레드 민감도 추가 | 현실성 증가 |
| 2 | Monte Carlo 리스크 리포트 추가 | 최악의 경우 추정 |
| 3 | walk-forward 검증 추가 | 과최적화 감소 |
| 4 | 변동성 regime 필터 추가 | 횡보장 손실 감소 |
| 5 | triple barrier 라벨링 실험 | 진입/청산 품질 개선 |
| 6 | meta-labeling 실험 | 나쁜 신호 필터링 |
| 7 | 동적 bet sizing | 손실 구간 방어 |
| 8 | 통계적 차익거래 전략 분리 구현 | 전략 다변화 |

## 핵심 결론

지금 단계에서 가장 중요한 것은 고급 AI를 바로 붙이는 것이 아닙니다.

가장 먼저 해야 할 일은 다음입니다.

1. 백테스트를 더 현실적으로 만들기
2. 과최적화를 줄이기
3. 손실 가능성을 확률적으로 보기
4. 변동성 상태에 따라 전략을 켜고 끄기
5. 좋은 신호와 나쁜 신호를 분리하기

즉, 현재 봇에는 다음 순서가 가장 좋습니다.

```text
Algorithmic Trading
→ Market Microstructure
→ Monte Carlo
→ Volatility Trading
→ Advances in Financial Machine Learning
→ Statistical Arbitrage
→ Reinforcement Learning / Stochastic Calculus / HFT Architecture
```

## 문서 사용법

- 개념을 처음 볼 때는 `뜻`과 `왜 중요한가` 위주로 읽습니다.
- 전략에 적용하려면 `현재 봇에 도입 가능한 부분`을 봅니다.
- 구현 우선순위를 정할 때는 `우선순위`와 `주의점`을 봅니다.
- 실제 코드 변경 전에는 항상 백테스트와 검증 기준을 먼저 정합니다.
