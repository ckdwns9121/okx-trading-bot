# Statistical Arbitrage — 통계적 차익거래

## 1. 한 줄 요약

**Statistical Arbitrage(통계적 차익거래)**는 두 개 이상의 자산 사이에 통계적으로 안정적인 관계가 있다고 보고, 그 관계가 일시적으로 깨졌을 때 평균회귀를 노리는 전략입니다.

방향성 예측보다는 상대가격의 괴리를 이용합니다.

## 2. 단순 예시

BTC와 ETH가 평소 비슷한 방향으로 움직인다고 합시다.

어느 날 BTC는 크게 올랐는데 ETH는 덜 올랐다면:

```text
BTC 숏
ETH 롱
```

이후 관계가 정상화되면 수익을 얻습니다.

핵심은 “BTC가 오를까 내릴까?”가 아니라 “BTC와 ETH의 관계가 정상으로 돌아올까?”입니다.

## 3. 대표 전략

### 3.1 Pairs Trading

두 자산의 spread를 계산하고, spread가 평균에서 크게 벗어나면 반대 포지션을 잡습니다.

```text
spread = price_A - hedge_ratio * price_B
```

spread가 너무 높으면:

```text
A 숏, B 롱
```

spread가 너무 낮으면:

```text
A 롱, B 숏
```

### 3.2 Cointegration

두 가격 시계열이 각각은 불안정해도 특정 조합은 안정적인 평균회귀 성질을 갖는 경우가 있습니다.

이 관계를 cointegration이라고 합니다.

Pairs trading에서는 correlation보다 cointegration이 더 중요합니다.

### 3.3 Basket Arbitrage

두 자산이 아니라 여러 자산의 조합으로 spread를 만듭니다.

예:

```text
롱: ETH, SOL
숏: BTC, BNB
```

### 3.4 Index Arbitrage

인덱스와 구성 종목 사이의 괴리를 거래합니다.

## 4. 핵심 개념

### 4.1 Correlation

두 자산 수익률이 같이 움직이는 정도입니다.

하지만 correlation이 높다고 pairs trading이 가능한 것은 아닙니다.

### 4.2 Cointegration

장기 균형 관계입니다.

통계적 차익거래에서는 보통 cointegration이 더 중요합니다.

### 4.3 Spread

거래 대상이 되는 괴리 값입니다.

### 4.4 Z-score

현재 spread가 평균에서 얼마나 떨어져 있는지를 표준편차 단위로 표시합니다.

```text
z = (spread - mean(spread)) / std(spread)
```

예:

```text
z > 2 → spread가 과도하게 높음
z < -2 → spread가 과도하게 낮음
```

### 4.5 Half-life

spread가 평균으로 돌아오는 데 걸리는 대략적인 시간입니다.

half-life가 너무 길면 실전 전략으로 쓰기 어렵습니다.

## 5. 장점

- 시장 방향에 덜 의존할 수 있음
- long/short 동시 운용으로 beta를 줄일 수 있음
- 변동성 장에서도 기회가 생김
- 포트폴리오 관점에서 안정적인 전략이 될 수 있음

## 6. 한계

- 관계가 영원히 유지된다는 보장이 없음
- 구조적 변화가 발생하면 큰 손실 가능
- 두 자산을 동시에 체결해야 함
- 수수료와 펀딩비가 중요함
- 공매도/선물 운용이 필요함
- 레버리지 리스크가 커질 수 있음

## 7. 암호화폐에서의 적용

암호화폐에서는 다음 pair를 볼 수 있습니다.

- BTC / ETH
- ETH / SOL
- BTC / crypto index
- 같은 코인의 spot / perpetual
- 같은 코인의 서로 다른 거래소 가격
- funding rate 차이

특히 perpetual futures에서는 펀딩비까지 고려해야 합니다.

## 8. 현재 봇에 필요한 기능

통계적 차익거래를 하려면 현재 봇에 다음이 필요합니다.

1. 다중 pair 동시 포지션 관리
2. pair spread 계산
3. hedge ratio 추정
4. cointegration test
5. z-score 진입/청산
6. 동시 주문 실행
7. pair-level 리스크 관리
8. 펀딩비 반영

현재 봇은 개별 pair 전략 중심이므로 구조 확장이 필요합니다.

## 9. 간단한 전략 구조

```text
1. BTC와 ETH의 최근 90일 가격 수집
2. 회귀로 hedge ratio 계산
3. spread = ETH - beta * BTC
4. spread z-score 계산
5. z > 2 이면 ETH 숏 + BTC 롱
6. z < -2 이면 ETH 롱 + BTC 숏
7. z가 0 근처로 돌아오면 청산
8. z가 더 벌어지면 손절
```

## 10. 필요한 통계 도구

- OLS regression
- Augmented Dickey-Fuller test
- Johansen cointegration test
- rolling z-score
- half-life estimation
- correlation stability analysis

Python 라이브러리:

- pandas
- numpy
- statsmodels
- scipy

## 11. 이 프로젝트에서의 우선순위

중간 정도입니다.

현재 단일 전략 성능이 아직 약하므로 먼저 해야 할 일:

1. 백테스트 현실화
2. 단일 전략 안정화
3. 신호별 성과 분석
4. 변동성 필터
5. 리스크 관리

그 다음 statistical arbitrage를 별도 전략 모듈로 추가하는 것이 좋습니다.

## 12. 요약

통계적 차익거래는 “가격 방향”보다 “자산 간 관계의 회복”에 베팅하는 전략입니다.

잘 만들면 안정적일 수 있지만, 관계 붕괴와 동시 체결 실패가 큰 리스크입니다.
