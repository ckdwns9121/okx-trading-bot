# RSI Bollinger Regime 리스크 제한 프로파일 검증 리포트

작성일: 2026-04-26  
원자료: `.omx/context/rsi-regime-risk-compare-results-20260426T131133Z.json`  
주의: 이 문서는 연구/검증용이며 투자 조언이나 실거래 권고가 아니다.

## 1. 목적

이전 워크포워드 검증에서 `rsi_bollinger_regime`은 가장 나은 후보였지만 최대 DD가 98.95%라 실거래 불가 판정을 받았다. 이번 작업의 목적은 수익 극대화가 아니라 **계좌 생존성 개선**이다.

## 2. 변경 내용

`rsi_bollinger_regime`에 명시적 리스크 프로파일을 추가했다.

- 기본값: 기존 동작 유지
- `risk_profile="limited"`:
  - `size_pct=25.0`
  - ATR 기반 TP: `tp_atr_mult=2.0`
  - ATR 기반 SL: `sl_atr_mult=1.0`
  - trailing stop: `2.5%`

즉, 기존 전략을 지우지 않고 별도 제한 모드만 추가했다.

## 3. 검증 조건

- 전략: `rsi_bollinger_regime`
- 비교 프로파일: `default`, `risk_limited`
- 대상: `BTC-USDT-SWAP`, `ETH-USDT-SWAP`, `SOL-USDT-SWAP`
- 타임프레임: `15m`, `1H`
- 구간: `2024_Q1`, `2024_Q3`, `2025_Q1`, `2025_Q3`, `2026_Q1`
- 실행 수: 2개 프로파일 × 3개 종목 × 2개 타임프레임 × 5개 구간 = 60회
- 결과: 60회 실행, 오류 0건
- 비용/체결 가정: 초기자본 10,000, 레버리지 2배, 수수료 0.05%, 슬리피지 0.05%, 펀딩 8시간당 0.01%

데이터 한계: `2026_Q1`의 `1H` 데이터는 일부 부족했다. BTC/ETH는 약 72.7%, SOL은 약 69.3% 커버리지로 실행되었다.

## 4. 핵심 결과

| 프로파일 | 총 PnL | 양수 실행 | 중앙 PnL | 평균 PF | 중앙 DD | 최대 DD | DD ≤ 40% 실행 | 판정 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `default` | 588,516.66 | 17/30 | 680.53 | 1.331 | 21.83% | 98.95% | 21/30 | 실거래 불가 |
| `risk_limited` | 208,825.96 | 26/30 | 1,023.87 | 4.886 | 2.48% | 23.69% | 30/30 | paper/demo 후보 |

리스크 제한 후 총 PnL은 줄었지만, 최대 DD가 98.95%에서 23.69%로 크게 낮아졌다. 양수 실행도 17/30에서 26/30으로 개선되었다.

## 5. 세부 해석

### 장점

- 최대 DD가 목표 기준인 40% 이하로 내려왔다.
- 30개 실행 전부 DD 40% 이하를 만족했다.
- 종목별로 BTC 9/10, ETH 8/10, SOL 9/10 수익 실행이었다.
- 1H는 15/15 전부 수익이었다.
- 손실 최악 구간도 `2024_Q3 SOL 15m -879.01`로 제한되었다.

### 비용

- 총 PnL은 `default` 대비 약 64.5% 줄었다.
- TP/SL/trailing stop으로 청산이 잦아져 기존 큰 수익 일부를 포기한다.
- 여전히 15m 구간에서는 일부 손실 실행이 남아 있다.

### 청산 구조 변화

- `default`: 대부분 신호 청산, stop-loss 청산 245회
- `risk_limited`: TP 793회, SL 680회, trailing stop 196회

리스크 제한 모드는 손실을 방치하지 않고 명시적 TP/SL/trailing stop으로 포지션을 더 자주 정리한다.

## 6. 판정

`risk_limited`는 **실거래 후보가 아니라 paper/demo 후보**로 승격 가능하다.

다만 바로 실거래는 금지한다. 백테스트는 체결 지연, 실시간 슬리피지, 주문 실패, API 장애를 완전히 반영하지 못한다. 다음 단계는 OKX demo 환경에서 최소 4주간 다음 지표를 관찰하는 것이다.

- 최대 DD가 25~30% 이내로 유지되는가
- 실제 체결 슬리피지가 백테스트 가정보다 크게 나빠지지 않는가
- SOL 15m 손실 구간이 반복되지 않는가
- API/봇 런타임 장애가 손실 확대로 이어지지 않는가

## 7. 다음 액션

1. `risk_profile="limited"`를 demo 전용 기본값으로 연결한다.
2. demo 런타임에서 일일 손실 한도와 전체 계좌 손실 한도를 추가한다.
3. 최소 4주 paper/demo 관찰 리포트를 만든다.
4. demo가 실패하면 파라미터 최적화가 아니라 거래 중단 조건부터 강화한다.

## 8. 검증 증거

- 원자료 대조: JSON 기준 60개 결과, 0개 오류, 2개 프로파일 요약 확인.
- 단위 테스트: `cd bot && ... pytest tests/test_rsi_bollinger_regime.py -q` → 4개 통과.
- 전체 백엔드 테스트: `cd bot && OKX_API_KEY=dummy OKX_SECRET=dummy OKX_PASSPHRASE=dummy /tmp/okx-bot-venv/bin/python -m pytest -q` → 29개 통과.
- 정적 확인: `python -m py_compile strategies/rsi_bollinger_regime.py tests/test_rsi_bollinger_regime.py` 통과.
- 독립 검증: Ralph verifier가 코드, 테스트, 원자료, 리포트 결론을 대조해 승인.
