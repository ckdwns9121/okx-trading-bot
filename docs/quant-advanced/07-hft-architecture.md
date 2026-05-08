# HFT Architecture — 고빈도매매 시스템 구조

## 1. 한 줄 요약

**HFT Architecture(고빈도매매 아키텍처)**는 밀리초 또는 마이크로초 단위로 시장 데이터를 처리하고 주문을 제출하는 초저지연 거래 시스템의 구조를 말합니다.

핵심 목표는 하나입니다.

```text
더 빨리 보고, 더 빨리 판단하고, 더 빨리 주문한다.
```

## 2. HFT는 무엇인가

HFT는 High-Frequency Trading의 약자입니다.

특징:

- 매우 짧은 보유 시간
- 초고속 주문 제출/취소
- 호가창 기반 의사결정
- 낮은 단위 수익을 높은 반복 횟수로 누적
- 인프라와 지연시간이 핵심 경쟁력

현재 이 OKX 봇의 5분봉 전략은 HFT가 아닙니다. 5분봉은 중저빈도 전략에 가깝습니다.

## 3. HFT 시스템 구성요소

### 3.1 Market Data Handler

거래소에서 실시간 데이터를 받는 모듈입니다.

데이터:

- order book
- trades
- tick data
- quotes
- funding updates

HFT에서는 REST가 아니라 WebSocket 또는 전용 feed를 사용합니다.

### 3.2 Strategy Engine

데이터를 받아 신호를 계산합니다.

HFT에서는 복잡한 모델보다 빠르고 단순한 로직이 선호됩니다.

### 3.3 Order Management System, OMS

주문 생성, 제출, 취소, 정정, 상태 추적을 담당합니다.

### 3.4 Risk Engine

주문 전 리스크를 체크합니다.

예:

- 최대 포지션
- 최대 손실
- 주문 속도 제한
- 거래소별 제한
- kill switch

### 3.5 Execution Engine

주문을 실제로 어떻게 넣을지 결정합니다.

예:

- market order
- limit order
- post-only
- iceberg
- split order
- cancel/replace

### 3.6 Monitoring

지연시간, 주문 실패, 체결 상태, 포지션 불일치 등을 감시합니다.

## 4. HFT에서 중요한 지표

### 4.1 Latency

신호 발생부터 주문 도달까지 걸리는 시간입니다.

```text
market data latency
strategy computation latency
order submission latency
exchange acknowledgement latency
```

### 4.2 Throughput

초당 처리 가능한 이벤트 수입니다.

### 4.3 Jitter

지연시간의 변동성입니다. 평균 latency가 낮아도 jitter가 크면 위험합니다.

### 4.4 Fill Ratio

제출한 주문 중 실제 체결된 비율입니다.

### 4.5 Cancel Ratio

주문 취소 비율입니다. 거래소 규정상 과도하면 제한을 받을 수 있습니다.

## 5. 기술 스택

진짜 HFT에서는 Python은 핵심 경로에 잘 쓰이지 않습니다.

자주 쓰는 언어:

- C++
- Rust
- Java
- Go

Python은 보통 다음에 사용합니다.

- 연구
- 백테스트
- 리포트
- 파라미터 탐색

## 6. 암호화폐 HFT의 현실

암호화폐 거래소에서는 전통 금융 HFT만큼 극단적인 co-location은 어렵지만, 여전히 속도는 중요합니다.

중요 요소:

- WebSocket 안정성
- 거래소 API rate limit
- 서버 위치
- 네트워크 지연
- 주문 실패 처리
- order book 재동기화
- timestamp 정합성

## 7. 현재 봇과의 차이

현재 봇:

```text
캔들 기반
분 단위 또는 5분 단위 판단
FastAPI + Python
DB 저장 중심
REST/WebSocket 일부 가능
```

HFT:

```text
tick/order book 기반
밀리초 단위 판단
초저지연 언어/인프라
메모리 중심
실시간 주문 취소/정정
```

따라서 현재 봇을 그대로 HFT로 만들기는 어렵습니다.

## 8. 그래도 도입할 수 있는 요소

HFT 전체는 아니어도 좋은 실행 구조는 도입할 수 있습니다.

### 8.1 WebSocket market data

REST polling보다 빠르고 안정적인 실시간 데이터 수신.

### 8.2 Order book spread filter

진입 전 spread가 너무 넓으면 주문하지 않음.

### 8.3 Execution latency logging

주문 요청부터 응답까지 시간을 기록.

### 8.4 Kill switch

이상 상황에서 즉시 모든 포지션을 닫거나 신규 주문을 중단.

### 8.5 Idempotent order handling

네트워크 오류 때 같은 주문이 중복 제출되지 않도록 처리.

이 프로젝트에는 일부 idempotency와 risk guard 구조가 이미 있습니다.

## 9. HFT 전략 예시

- market making
- order book imbalance
- latency arbitrage
- statistical arbitrage at tick level
- spread capture
- queue position strategy

하지만 이런 전략은 매우 고난도입니다.

## 10. 필요한 데이터

- tick data
- full depth order book
- order acknowledgements
- fill reports
- cancel reports
- latency timestamps
- network metrics

캔들 데이터만으로는 HFT 전략을 만들 수 없습니다.

## 11. 장점

- 시장 비효율을 빠르게 포착 가능
- 짧은 보유 시간으로 방향 리스크 감소 가능
- 체결 전략 최적화 가능

## 12. 한계

- 인프라 비용이 큼
- 구현 난이도가 매우 높음
- 거래소 제한에 민감함
- 작은 버그가 큰 손실로 이어질 수 있음
- 개인/소규모 프로젝트에는 과할 수 있음

## 13. 이 프로젝트에서의 우선순위

HFT 전체 구현 우선순위는 낮습니다.

하지만 다음은 도입 가치가 높습니다.

1. WebSocket 기반 실시간 캔들/호가 수신
2. spread/depth 필터
3. 주문 지연시간 로깅
4. 주문 실패 복구 강화
5. kill switch 강화
6. 실전 체결가와 기대가 차이 저장

## 14. 요약

HFT Architecture는 초저지연 시스템을 만드는 분야입니다.

현재 봇은 HFT가 아니지만, HFT에서 배우는 실행 품질, 리스크 통제, 지연시간 관리 개념은 충분히 도입할 가치가 있습니다.
