# Volatility Trading — 변동성 트레이딩

## 1. 한 줄 요약

**Volatility Trading(변동성 트레이딩)**은 가격의 방향 자체보다 가격이 얼마나 크게 움직일지를 거래하거나, 변동성 상태에 따라 전략을 조절하는 방식입니다.

일반적인 방향성 전략은 이렇게 묻습니다.

```text
가격이 오를까 내릴까?
```

변동성 트레이딩은 이렇게 묻습니다.

```text
가격이 크게 움직일까 조용할까?
현재 변동성은 너무 높은가 낮은가?
변동성이 확장될 가능성이 있는가?
```

## 2. 변동성이란

변동성은 가격 변화의 크기입니다.

대표적인 측정 방법:

- 표준편차
- ATR
- realized volatility
- Bollinger Band width
- Parkinson volatility
- Garman-Klass volatility
- implied volatility

암호화폐 현물/선물 전략에서는 보통 다음이 실용적입니다.

- ATR
- 수익률 표준편차
- 볼린저밴드 폭
- 고저가 range

## 3. Historical Volatility와 Implied Volatility

### 3.1 Historical Volatility

과거 가격 움직임으로 계산한 변동성입니다.

예:

```text
최근 20개 5분봉 수익률의 표준편차
```

### 3.2 Implied Volatility

옵션 가격에 내재된 미래 변동성 기대치입니다.

옵션 시장에서 중요합니다.

현재 OKX 선물 봇에서는 옵션을 직접 다루지 않으므로 historical volatility가 우선입니다.

## 4. 트레이딩에서 변동성의 역할

### 4.1 진입 필터

변동성이 너무 낮으면 돌파 신호가 가짜일 가능성이 큽니다.

예:

```text
볼린저밴드 폭 < 0.3% → 진입 금지
```

### 4.2 포지션 사이징

변동성이 높을수록 포지션 크기를 줄입니다.

예:

```text
size = target_volatility / current_volatility
```

### 4.3 익절/손절 거리

고정 손절보다 ATR 기반 손절이 더 자연스럽습니다.

```text
손절 = entry - ATR * 1.5
익절 = entry + ATR * 2.5
```

### 4.4 전략 선택

변동성이 낮은 압축 구간에서는 breakout 전략이 유리할 수 있고, 변동성이 이미 과도하게 높은 구간에서는 추격 진입이 위험할 수 있습니다.

## 5. 대표 전략

### 5.1 Volatility Breakout

일정 range를 넘는 강한 움직임에 진입합니다.

예:

```text
오늘 시가 + 전일 range * k 돌파 시 매수
```

### 5.2 Bollinger Band Squeeze

볼린저밴드 폭이 좁아진 후 확장될 때 진입합니다.

구조:

```text
밴드폭이 최근 하위 20% 수준으로 축소
이후 가격이 상단 밴드를 돌파
거래량 증가 확인
진입
```

### 5.3 Mean Reversion After Volatility Spike

변동성이 갑자기 커진 뒤 과도한 가격 움직임이 평균으로 회귀하는 것을 노립니다.

### 5.4 Volatility Targeting

전략 자체보다 리스크 관리에 가깝습니다.

```text
현재 변동성이 목표보다 높으면 size 축소
현재 변동성이 목표보다 낮으면 size 확대
```

## 6. 현재 봇에서 이미 쓰는 요소

현재 프로젝트에는 다음 요소가 일부 있습니다.

- ATR 계산
- 볼린저밴드 전략
- 볼린저밴드 폭 필터
- trailing stop
- volatility-based size scaling 설정 일부

하지만 아직 완전한 변동성 트레이딩은 아닙니다.

## 7. 5분봉 7일선 전략과 연결

현재 5분봉 7일선 전략에 볼린저밴드를 붙인 것은 변동성 필터의 시작입니다.

현재 구조:

```text
7일선 돌파
다음 봉 확인
볼린저밴드 폭이 충분한지 확인
상단 밴드까지 공간이 있는지 확인
상단 밴드를 익절 기준으로 사용
```

이는 변동성 트레이딩의 아주 실용적인 초급 적용입니다.

## 8. 더 발전시키는 방법

### 8.1 Bollinger Band Width Percentile

절대 밴드폭이 아니라 최근 N개 구간에서 현재 밴드폭이 어느 분위수인지 봅니다.

```text
현재 bb_width가 최근 30일 중 상위 40% 이상일 때만 진입
```

### 8.2 ATR Regime Filter

```text
현재 ATR / 가격 > 최소 기준
현재 ATR이 너무 과도하면 진입 금지
```

### 8.3 Volatility Expansion Confirmation

단순히 변동성이 큰 것이 아니라 확장 중인지 확인합니다.

```text
bb_width_now > bb_width_prev
```

### 8.4 Volatility-based Position Sizing

```text
size_pct = base_size * target_vol / current_vol
```

## 9. 장점

- 횡보장에서 가짜 돌파를 줄일 수 있음
- 시장 상태에 따라 전략을 조절할 수 있음
- 손절/익절을 시장 상황에 맞게 조정 가능
- 포지션 사이징이 더 안정적임

## 10. 한계

- 변동성이 높다고 방향이 맞는 것은 아님
- 변동성 지표도 후행적임
- 너무 많은 필터를 붙이면 거래 기회가 사라짐
- 파라미터 최적화에 취약함

## 11. 이 프로젝트에서 우선순위

매우 높습니다.

추천 구현:

1. 볼린저밴드 폭 필터
2. ATR 기반 포지션 사이징
3. bb_width percentile
4. volatility regime 분류
5. 변동성별 전략 성과 리포트
6. Monte Carlo와 결합한 risk sizing

## 12. 요약

변동성 트레이딩은 “방향 맞추기”만 하던 전략을 “시장 상태에 맞는 전략”으로 바꾸는 핵심 도구입니다.

지금 봇에는 가장 먼저 도입할 만한 고급 분야입니다.
