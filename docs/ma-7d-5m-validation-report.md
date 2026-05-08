# MA 7D 5m Validation Report

작성일: 2026-05-08T12:13:53+00:00

## 목적

`ma_7d_5m` 전략을 실거래/데모 시작 전에 최근 OKX 5분봉으로 독립 검증했다. 이 검증은 주문을 내지 않고 public candle만 가져와 인메모리 백테스트로 실행한다.

## 설정

- Pairs: BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP
- Timeframe: 5m
- Window days: 21 × 2 windows
- Initial balance: 10000.0
- Leverage: 2
- Fee rate: 0.0005
- Slippage pct: 0.05

## 결과

| Window | Pair | Scenario | Candles | Trades | PnL | Return | Win | Max DD | Sharpe | Long/Short |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| recent | BTC-USDT-SWAP | default_long | 6049 | 0 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0/0 |
| recent | BTC-USDT-SWAP | limited_long | 6049 | 0 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0/0 |
| recent | BTC-USDT-SWAP | limited_both | 6049 | 4 | -24.10 | -0.24% | 25.0% | 0.29% | -11.48 | 0/4 |
| recent | ETH-USDT-SWAP | default_long | 6049 | 2 | -157.81 | -1.58% | 0.0% | 1.68% | -57.91 | 2/0 |
| recent | ETH-USDT-SWAP | limited_long | 6049 | 2 | -34.86 | -0.35% | 0.0% | 0.37% | -127.95 | 2/0 |
| recent | ETH-USDT-SWAP | limited_both | 6049 | 3 | -36.75 | -0.37% | 0.0% | 0.40% | -28.92 | 0/3 |
| recent | SOL-USDT-SWAP | default_long | 6049 | 1 | 78.43 | 0.78% | 100.0% | 0.00% | 0.00 | 1/0 |
| recent | SOL-USDT-SWAP | limited_long | 6049 | 1 | 0.15 | 0.00% | 100.0% | 0.01% | 0.00 | 1/0 |
| recent | SOL-USDT-SWAP | limited_both | 6049 | 5 | -66.77 | -0.67% | 20.0% | 0.73% | -20.68 | 1/4 |
| prior_1 | BTC-USDT-SWAP | default_long | 6049 | 2 | -3.16 | -0.03% | 50.0% | 0.53% | -0.38 | 2/0 |
| prior_1 | BTC-USDT-SWAP | limited_long | 6049 | 2 | -0.75 | -0.01% | 50.0% | 0.13% | -0.36 | 2/0 |
| prior_1 | BTC-USDT-SWAP | limited_both | 6049 | 0 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0/0 |
| prior_1 | ETH-USDT-SWAP | default_long | 6049 | 9 | -325.77 | -3.26% | 22.2% | 3.84% | -16.80 | 9/0 |
| prior_1 | ETH-USDT-SWAP | limited_long | 6049 | 9 | -82.31 | -0.82% | 22.2% | 0.97% | -16.69 | 9/0 |
| prior_1 | ETH-USDT-SWAP | limited_both | 6049 | 9 | -73.89 | -0.74% | 22.2% | 0.89% | -17.01 | 8/1 |
| prior_1 | SOL-USDT-SWAP | default_long | 6049 | 10 | -52.86 | -0.53% | 40.0% | 3.95% | -0.77 | 10/0 |
| prior_1 | SOL-USDT-SWAP | limited_long | 6049 | 10 | -18.40 | -0.18% | 40.0% | 0.75% | -1.55 | 10/0 |
| prior_1 | SOL-USDT-SWAP | limited_both | 6049 | 11 | -59.54 | -0.60% | 36.4% | 0.92% | -5.28 | 9/2 |

## 판정

- Positive runs: 2/18
- Worst max DD: 3.95%
- Best raw PnL: default_long / SOL-USDT-SWAP / recent = 78.43
- Median-like PnL row: limited_both / BTC-USDT-SWAP / recent = -24.10
- 결론: **demo 후보 탈락/보류**. 수익 일관성 또는 DD 조건을 통과하지 못했다.

## 다음 단계

1. 이 전략은 통과 전까지 OKX demo 자동 실행 목록에 넣지 않는다.
2. 개선한다면 파라미터 최적화보다 시장 레짐/거래 시간 필터를 먼저 검증한다.
3. demo 후보는 기존 `rsi_bollinger_regime` limited를 유지한다.
