# Advances in Financial Machine Learning — 금융 머신러닝 고급 기법

## 1. 한 줄 요약

**Advances in Financial Machine Learning**은 Marcos López de Prado의 책 제목으로도 유명하며, 금융 데이터에서 머신러닝을 사용할 때 발생하는 특수한 문제를 다루는 고급 방법론입니다.

일반 머신러닝을 금융에 그대로 적용하면 자주 실패합니다.

이유:

- 데이터가 독립적이지 않음
- 시계열 누수가 발생하기 쉬움
- 라벨링이 어려움
- 수익 기회가 희박함
- 과최적화가 매우 쉬움
- 백테스트가 쉽게 왜곡됨

## 2. 일반 ML과 금융 ML의 차이

일반 이미지 분류 문제에서는 데이터가 비교적 독립적입니다.

하지만 금융 데이터는 시간 순서가 중요합니다.

```text
오늘 가격은 어제 가격과 관련이 있음
오늘 변동성은 어제 변동성과 관련이 있음
훈련 데이터와 검증 데이터가 겹치면 미래 정보 누수가 발생함
```

그래서 금융 ML은 데이터 분할, 라벨링, 검증 방법이 매우 중요합니다.

## 3. 핵심 개념

### 3.1 Triple Barrier Labeling

일반적인 라벨링은 단순합니다.

```text
N봉 뒤 가격이 올랐으면 1
내렸으면 0
```

하지만 이 방식은 비현실적입니다.

실전 거래에는 익절, 손절, 시간 제한이 있습니다.

Triple Barrier Labeling은 세 개의 장벽을 둡니다.

1. 상단 장벽: 익절
2. 하단 장벽: 손절
3. 수직 장벽: 시간 만료

예:

```text
진입 시점 이후
먼저 +2%에 닿으면 label = 1
먼저 -1%에 닿으면 label = 0 또는 -1
둘 다 안 닿고 24봉이 지나면 시간 만료
```

이 방식은 실제 거래 결과와 더 가깝습니다.

### 3.2 Meta-labeling

Meta-labeling은 “진입 신호를 ML이 직접 만들지 않고, 기존 전략 신호가 좋은 신호인지 나쁜 신호인지 판단”하는 방식입니다.

예:

1. 룰 전략이 후보 신호 생성
2. 각 후보 신호에 대해 feature 계산
3. 결과를 triple barrier로 라벨링
4. ML 모델이 “이 신호를 거래할지 말지” 학습

즉:

```text
룰 전략 = 방향 제안
ML 모델 = 진입 여부 필터
```

현재 봇에는 이 방식이 가장 현실적입니다.

### 3.3 Purged Cross Validation

시계열 금융 데이터는 train/test가 조금만 겹쳐도 정보 누수가 생길 수 있습니다.

예를 들어 어떤 신호의 결과가 다음 20봉 동안 결정된다면, 그 20봉과 겹치는 데이터를 검증 세트에 넣으면 안 됩니다.

Purging은 이렇게 겹치는 구간을 제거하는 것입니다.

### 3.4 Embargo

train/test split 경계 근처의 데이터를 일부 비워두는 방식입니다.

목적은 경계 근처 정보 누수를 줄이는 것입니다.

### 3.5 Bet Sizing

ML 모델이 단순히 진입/비진입만 결정하는 것이 아니라, 확률에 따라 포지션 크기를 정하는 것입니다.

예:

```text
모델이 성공 확률 52% 예측 → size 10%
성공 확률 65% 예측 → size 30%
성공 확률 80% 예측 → size 60%
```

### 3.6 Fractional Differentiation

금융 시계열을 정상성 있게 만들면서도 원래 정보는 최대한 보존하려는 방법입니다.

일반 차분은 정보 손실이 큽니다.

Fractional differentiation은 그 중간 방식입니다.

## 4. 현재 5분봉 7일선 전략에 적용하는 방법

현재 전략은 다음과 같습니다.

```text
5분봉 7일선 돌파
다음 봉 확인
볼린저밴드 필터
볼린저밴드 익절
```

이를 meta-labeling 구조로 바꾸면:

### 4.1 Primary Model

기존 룰 전략이 primary model입니다.

```text
7일선 돌파 + 다음 봉 확인 = 후보 신호
```

### 4.2 Feature 생성

후보 신호 시점마다 다음 feature를 저장합니다.

```text
ma_distance_pct
ma_slope_pct
bb_width_pct
bb_room_pct
atr_pct
volume_ratio
recent_return_1
recent_return_3
recent_return_12
funding_rate
spread_pct
regime_label
```

### 4.3 Label 생성

Triple barrier로 라벨링합니다.

예:

```text
익절: +1.2 ATR 또는 상단 볼린저밴드
손절: -0.8 ATR 또는 7일선 이탈
시간 제한: 24개 5분봉
```

결과:

```text
좋은 신호 = 1
나쁜 신호 = 0
```

### 4.4 모델 학습

간단한 모델부터 시작합니다.

- Logistic Regression
- Random Forest
- XGBoost 또는 LightGBM

처음부터 deep learning은 추천하지 않습니다.

### 4.5 실전 적용

```text
룰 전략 후보 신호 발생
feature 계산
모델이 성공 확률 예측
확률이 threshold 이상이면 진입
확률에 따라 size 조절
```

## 5. 왜 유용한가

현재 전략은 모든 돌파를 비슷하게 봅니다.

하지만 실제로는 좋은 돌파와 나쁜 돌파가 있습니다.

예:

좋은 돌파:

```text
변동성 확장 중
상단 밴드까지 공간 있음
거래량 증가
상위 추세 상승
스프레드 낮음
```

나쁜 돌파:

```text
이미 상단 밴드 과열
거래량 없음
밴드폭 너무 좁음
상위 추세 하락
스프레드 넓음
```

Meta-labeling은 이 차이를 학습합니다.

## 6. 필요한 데이터 구조

신호별로 별도 테이블을 만들면 좋습니다.

예:

```text
strategy_signals
- id
- timestamp
- pair
- timeframe
- strategy_name
- signal_side
- entry_price
- ma_distance_pct
- ma_slope_pct
- bb_width_pct
- bb_room_pct
- atr_pct
- volume_ratio
- funding_rate
- label
- outcome_pnl
- bars_to_exit
- exit_reason
```

이 테이블이 있어야 금융 ML을 제대로 시작할 수 있습니다.

## 7. 장점

- 룰 전략을 완전히 버리지 않아도 됨
- 모델이 할 일을 제한하므로 과최적화 위험이 줄어듦
- 신호 품질을 정량적으로 분석 가능
- 포지션 사이징으로 확장 가능
- 기존 백테스트 엔진과 결합하기 좋음

## 8. 한계

- 충분한 신호 데이터가 필요함
- feature가 나쁘면 모델도 나쁨
- 라벨 정의에 따라 결과가 크게 달라짐
- 여전히 과최적화 위험이 있음
- walk-forward 검증이 필수임

## 9. 이 프로젝트에서의 추천 구현 순서

1. 백테스트 중 후보 신호 feature 저장
2. triple barrier label 생성
3. feature/outcome 리포트 생성
4. 단순 rule threshold 탐색
5. logistic regression meta-model
6. purged walk-forward validation
7. 모델 확률 기반 진입 필터
8. 확률 기반 bet sizing

## 10. 절대 피해야 할 것

- 미래 수익률을 feature에 넣기
- 랜덤 train/test split 사용
- 전체 기간 최적화 후 같은 기간 성과 보고
- 수수료/슬리피지 무시
- 신호 수가 적은데 복잡한 모델 사용
- accuracy만 보고 모델 평가

금융 ML에서는 accuracy보다 다음이 중요합니다.

- precision
- expected value
- drawdown
- turnover
- probability calibration
- out-of-sample PnL

## 11. 현재 봇에 가장 적합한 적용

가장 현실적인 첫 적용은 다음입니다.

```text
5분봉 7일선 돌파 전략을 primary signal로 사용
신호 시점 feature 저장
triple barrier로 라벨링
나쁜 돌파를 거르는 meta-labeling 모델 학습
```

이는 RL보다 훨씬 현실적이고, 현재 코드베이스와도 잘 맞습니다.

## 12. 요약

Advances in Financial Machine Learning의 핵심은 “금융 데이터에 맞는 검증과 라벨링”입니다.

현재 봇이 고급 단계로 가려면 가장 먼저 도입할 만한 내용은 다음 세 가지입니다.

1. Triple barrier labeling
2. Meta-labeling
3. Purged walk-forward validation
