# 전체 전략 백테스트 비교 리포트

- 작성일: `2026-05-08T12:22:23+00:00`
- 데이터 구간(UTC): `2026-02-07T12:20:00` ~ `2026-05-08T12:20:00`
- 종목: `BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP`
- 시간봉: `15m, 1H`
- 전략 수: `16`개
- 비용/체결 가정: 수수료 `0.0005`, 슬리피지 `0.05%`, 펀딩 `0.0001/8h`, 유동성 영향 `0.1`

## 해석 기준

- 이 표는 연구용 백테스트 결과이며 수익 보장이나 실거래 권고가 아니다.
- `chronos_regime_hybrid`는 현재 프로젝트 기본값에 맞춰 `chronos_enabled=false` fallback 경로로 비교했다.
- `ma_7d_5m`은 원래 5분봉 전용 전략이지만, 전체 전략 공통 비교를 위해 같은 시간봉에서도 실행했다.
- `데이터부족/오류`는 해당 전략의 lookback보다 candle 수가 부족하거나 실행 중 오류가 발생한 경우다.

## 핵심 결론

- 단순 합산 PnL 1위는 `example_rsi`이지만 Max DD가 `97.44%`라서 바로 demo/live 후보로 보지 않는다.
- paper 후보와 연구 후보 모두 없다. 수익성보다 생존성 기준에서 전체적으로 불안정하다.
- 기존 demo 관찰 후보인 `rsi_bollinger_regime`은 이번 비교에서도 양수 실행 `5/6`이지만 Max DD `68.49%`라서 `risk_profile=limited` 조건을 계속 유지해야 한다.

## 전략별 종합 순위

| 순위 | 전략 | 판정 | 실행 | 양수 실행 | 합산 PnL | 평균 PnL | 중앙 PnL | 평균 PF | 평균 Sharpe | 평균 승률 | Max DD | 거래수 | 최고 Run | 최악 Run |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `example_rsi` | 고위험 관찰 | 6/6 | 4 | 1,064,220.40 | 177,370.07 | 43,203.25 | 1.23 | 0.66 | 48.2% | 97.44% | 2903 | ETH-USDT-SWAP 15m 863,811.68 | BTC-USDT-SWAP 1H -3,549.36 |
| 2 | `rsi_bollinger_combo` | 고위험 관찰 | 6/6 | 5 | 160,616.40 | 26,769.40 | 16,786.49 | 1.50 | 1.77 | 64.1% | 46.03% | 946 | ETH-USDT-SWAP 1H 92,250.05 | BTC-USDT-SWAP 1H -2,295.92 |
| 3 | `mean_reversion` | 고위험 관찰 | 6/6 | 5 | 151,387.52 | 25,231.25 | 15,697.29 | 1.41 | 1.40 | 61.6% | 80.63% | 1090 | ETH-USDT-SWAP 1H 76,217.49 | BTC-USDT-SWAP 1H -465.67 |
| 4 | `bollinger_band` | 고위험 관찰 | 6/6 | 4 | 57,380.37 | 9,563.39 | 4,207.18 | 1.13 | 0.48 | 56.7% | 43.99% | 784 | BTC-USDT-SWAP 15m 40,723.14 | SOL-USDT-SWAP 1H -2,271.24 |
| 5 | `chronos_regime_hybrid` | 고위험 관찰 | 6/6 | 5 | 43,711.05 | 7,285.17 | 4,775.51 | 1.57 | 1.64 | 52.3% | 43.25% | 529 | ETH-USDT-SWAP 1H 25,834.31 | BTC-USDT-SWAP 1H -1,100.03 |
| 6 | `rsi_bollinger_regime` | 고위험 관찰 | 6/6 | 5 | 25,831.22 | 4,305.20 | 4,474.44 | 1.35 | 1.34 | 52.5% | 68.49% | 530 | SOL-USDT-SWAP 15m 9,842.72 | BTC-USDT-SWAP 1H -749.77 |
| 7 | `ma_7d_5m` | 탈락/보류 | 6/6 | 2 | -3,264.32 | -544.05 | 0.00 | 0.64 | -0.37 | 21.2% | 41.98% | 36 | BTC-USDT-SWAP 15m 563.49 | ETH-USDT-SWAP 15m -4,014.78 |
| 8 | `ict_liquidity_fvg` | 탈락/보류 | 6/6 | 0 | -3,343.37 | -557.23 | -517.59 | 0.44 | -6.14 | 26.7% | 13.99% | 211 | BTC-USDT-SWAP 1H -165.85 | ETH-USDT-SWAP 15m -1,066.54 |
| 9 | `elliott_wave_fib` | 탈락/보류 | 6/6 | 1 | -12,139.97 | -2,023.33 | -2,806.55 | 0.80 | -1.61 | 43.2% | 52.48% | 316 | ETH-USDT-SWAP 1H 1,569.06 | SOL-USDT-SWAP 1H -3,239.71 |
| 10 | `multi_factor` | 탈락/보류 | 6/6 | 1 | -15,405.76 | -2,567.63 | -1,917.38 | 0.77 | -1.66 | 39.6% | 75.15% | 956 | BTC-USDT-SWAP 15m 199.76 | ETH-USDT-SWAP 15m -6,628.94 |
| 11 | `livermore` | 탈락/보류 | 6/6 | 0 | -45,804.59 | -7,634.10 | -8,068.73 | 0.28 | -5.85 | 24.4% | 99.38% | 697 | BTC-USDT-SWAP 1H -5,251.70 | ETH-USDT-SWAP 15m -9,766.91 |
| 12 | `volume_momentum` | 탈락/보류 | 6/6 | 0 | -46,798.40 | -7,799.73 | -8,822.22 | 0.20 | -6.76 | 21.8% | 99.94% | 603 | BTC-USDT-SWAP 1H -3,318.89 | ETH-USDT-SWAP 15m -9,881.70 |
| 13 | `breakout_strategy` | 탈락/보류 | 6/6 | 0 | -51,714.50 | -8,619.08 | -8,781.70 | 0.16 | -8.43 | 21.6% | 99.67% | 688 | SOL-USDT-SWAP 1H -6,978.42 | ETH-USDT-SWAP 15m -9,826.25 |
| 14 | `multi_ema` | 탈락/보류 | 6/6 | 0 | -52,346.05 | -8,724.34 | -9,244.37 | 0.19 | -6.22 | 17.7% | 99.93% | 1218 | BTC-USDT-SWAP 1H -5,212.65 | SOL-USDT-SWAP 15m -9,880.18 |
| 15 | `example_sma_cross` | 탈락/보류 | 6/6 | 0 | -53,021.53 | -8,836.92 | -9,291.08 | 0.27 | -4.73 | 23.1% | 99.83% | 1415 | BTC-USDT-SWAP 1H -6,144.05 | SOL-USDT-SWAP 15m -9,839.52 |
| 16 | `macd_strategy` | 탈락/보류 | 6/6 | 0 | -53,618.66 | -8,936.44 | -9,283.36 | 0.30 | -4.09 | 26.8% | 100.00% | 2088 | BTC-USDT-SWAP 1H -6,252.92 | SOL-USDT-SWAP 15m -9,878.34 |

## Run 상세

| 전략 | 종목 | TF | 상태 | Candles | PnL | Return | 승률 | Max DD | PF | Sharpe | 거래수 | 주요 청산 | 비고 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `bollinger_band` | BTC-USDT-SWAP | 15m | ok | 8640 | 40,723.14 | 407.23% | 71.4% | 26.90% | 1.53 | 2.42 | 220 | signal_flip:193, stop_loss_pct:26, end_of_data:1 |  |
| `bollinger_band` | BTC-USDT-SWAP | 1H | ok | 2160 | -1,126.77 | -11.27% | 55.8% | 35.11% | 0.91 | -0.66 | 52 | signal_flip:32, stop_loss_pct:19, end_of_data:1 |  |
| `bollinger_band` | ETH-USDT-SWAP | 15m | ok | 8640 | 4,447.00 | 44.47% | 60.7% | 43.99% | 1.09 | 0.50 | 214 | signal_flip:150, stop_loss_pct:64 |  |
| `bollinger_band` | ETH-USDT-SWAP | 1H | ok | 2160 | 11,640.88 | 116.41% | 43.4% | 43.83% | 1.40 | 1.81 | 53 | stop_loss_pct:29, signal_flip:24 |  |
| `bollinger_band` | SOL-USDT-SWAP | 15m | ok | 8640 | 3,967.36 | 39.67% | 55.6% | 36.81% | 1.09 | 0.55 | 196 | signal_flip:147, stop_loss_pct:48, end_of_data:1 |  |
| `bollinger_band` | SOL-USDT-SWAP | 1H | ok | 2160 | -2,271.24 | -22.71% | 53.1% | 43.59% | 0.78 | -1.71 | 49 | signal_flip:26, stop_loss_pct:22, end_of_data:1 |  |
| `breakout_strategy` | BTC-USDT-SWAP | 15m | ok | 8640 | -9,267.35 | -92.67% | 24.2% | 94.95% | 0.26 | -5.60 | 178 | signal_flip:163, stop_loss_pct:14, end_of_data:1 |  |
| `breakout_strategy` | BTC-USDT-SWAP | 1H | ok | 2160 | -7,699.71 | -77.00% | 20.4% | 79.81% | 0.12 | -11.94 | 54 | signal_flip:42, stop_loss_pct:11, end_of_data:1 |  |
| `breakout_strategy` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,826.25 | -98.26% | 18.1% | 99.67% | 0.17 | -5.11 | 193 | signal_flip:135, stop_loss_pct:57, end_of_data:1 |  |
| `breakout_strategy` | ETH-USDT-SWAP | 1H | ok | 2160 | -8,296.05 | -82.96% | 22.5% | 85.14% | 0.05 | -12.85 | 40 | stop_loss_pct:21, signal_flip:18, end_of_data:1 |  |
| `breakout_strategy` | SOL-USDT-SWAP | 15m | ok | 8640 | -9,646.72 | -96.47% | 25.0% | 97.72% | 0.11 | -6.65 | 176 | signal_flip:130, stop_loss_pct:45, end_of_data:1 |  |
| `breakout_strategy` | SOL-USDT-SWAP | 1H | ok | 2160 | -6,978.42 | -69.78% | 19.1% | 73.68% | 0.27 | -8.46 | 47 | signal_flip:32, stop_loss_pct:14, end_of_data:1 |  |
| `chronos_regime_hybrid` | BTC-USDT-SWAP | 15m | ok | 8640 | 4,866.89 | 48.67% | 58.6% | 13.72% | 1.59 | 2.68 | 145 | signal:144, end_of_data:1 |  |
| `chronos_regime_hybrid` | BTC-USDT-SWAP | 1H | ok | 2160 | -1,100.03 | -11.00% | 45.5% | 20.92% | 0.65 | -2.48 | 33 | signal:32, stop_loss_pct:1 |  |
| `chronos_regime_hybrid` | ETH-USDT-SWAP | 15m | ok | 8640 | 2,949.64 | 29.50% | 55.4% | 43.25% | 1.11 | 0.50 | 157 | signal:144, stop_loss_pct:11, signal_flip:2 |  |
| `chronos_regime_hybrid` | ETH-USDT-SWAP | 1H | ok | 2160 | 25,834.31 | 258.34% | 45.2% | 20.09% | 2.85 | 4.04 | 31 | signal:26, stop_loss_pct:5 |  |
| `chronos_regime_hybrid` | SOL-USDT-SWAP | 15m | ok | 8640 | 6,476.11 | 64.76% | 47.6% | 24.94% | 1.35 | 1.53 | 124 | signal:119, stop_loss_pct:3, signal_flip:2 |  |
| `chronos_regime_hybrid` | SOL-USDT-SWAP | 1H | ok | 2160 | 4,684.13 | 46.84% | 61.5% | 13.05% | 1.85 | 3.55 | 39 | signal:37, signal_flip:1, stop_loss_pct:1 |  |
| `elliott_wave_fib` | BTC-USDT-SWAP | 15m | ok | 8640 | -2,735.63 | -27.36% | 47.2% | 34.97% | 0.69 | -2.35 | 53 | signal:24, stop_loss_pct:15, signal_flip:14 |  |
| `elliott_wave_fib` | BTC-USDT-SWAP | 1H | ok | 2160 | -2,877.48 | -28.77% | 41.9% | 33.77% | 0.63 | -2.99 | 31 | stop_loss_pct:13, signal_flip:9, signal:8 |  |
| `elliott_wave_fib` | ETH-USDT-SWAP | 15m | ok | 8640 | -2,901.08 | -29.01% | 42.3% | 46.05% | 0.85 | -1.02 | 78 | stop_loss_pct:37, signal:25, signal_flip:15 |  |
| `elliott_wave_fib` | ETH-USDT-SWAP | 1H | ok | 2160 | 1,569.06 | 15.69% | 35.5% | 31.91% | 1.15 | 0.85 | 31 | stop_loss_pct:17, signal:10, signal_flip:3 |  |
| `elliott_wave_fib` | SOL-USDT-SWAP | 15m | ok | 8640 | -1,955.14 | -19.55% | 51.6% | 52.48% | 0.90 | -0.63 | 91 | stop_loss_pct:36, signal:35, signal_flip:20 |  |
| `elliott_wave_fib` | SOL-USDT-SWAP | 1H | ok | 2160 | -3,239.71 | -32.40% | 40.6% | 44.93% | 0.59 | -3.54 | 32 | stop_loss_pct:16, signal_flip:8, signal:7 |  |
| `example_rsi` | BTC-USDT-SWAP | 15m | ok | 8640 | -1,102.91 | -11.03% | 46.8% | 51.67% | 0.96 | -0.20 | 761 | signal:469, sl:187, tp:81 |  |
| `example_rsi` | BTC-USDT-SWAP | 1H | ok | 2160 | -3,549.36 | -35.49% | 45.9% | 45.08% | 0.74 | -1.80 | 181 | signal:87, sl:43, trailing_stop:36 |  |
| `example_rsi` | ETH-USDT-SWAP | 15m | ok | 8640 | 863,811.68 | 8,638.12% | 50.3% | 57.61% | 1.36 | 1.15 | 780 | signal:397, sl:187, tp:124 |  |
| `example_rsi` | ETH-USDT-SWAP | 1H | ok | 2160 | 118,654.49 | 1,186.54% | 51.3% | 35.64% | 1.71 | 2.40 | 199 | signal:81, trailing_stop:61, sl:31 |  |
| `example_rsi` | SOL-USDT-SWAP | 15m | ok | 8640 | 36,845.64 | 368.46% | 45.9% | 97.44% | 1.05 | 0.15 | 806 | signal:402, trailing_stop:195, sl:139 |  |
| `example_rsi` | SOL-USDT-SWAP | 1H | ok | 2160 | 49,560.86 | 495.61% | 48.9% | 42.99% | 1.55 | 2.25 | 176 | trailing_stop:71, signal:63, sl:27 |  |
| `example_sma_cross` | BTC-USDT-SWAP | 15m | ok | 8640 | -8,841.18 | -88.41% | 24.1% | 94.05% | 0.42 | -3.39 | 378 | signal_flip:362, stop_loss_pct:15, end_of_data:1 |  |
| `example_sma_cross` | BTC-USDT-SWAP | 1H | ok | 2160 | -6,144.05 | -61.44% | 31.3% | 67.84% | 0.47 | -4.44 | 83 | signal_flip:70, stop_loss_pct:12, end_of_data:1 |  |
| `example_sma_cross` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,749.31 | -97.49% | 21.7% | 99.79% | 0.29 | -3.43 | 382 | signal_flip:309, stop_loss_pct:72, end_of_data:1 |  |
| `example_sma_cross` | ETH-USDT-SWAP | 1H | ok | 2160 | -9,740.99 | -97.41% | 15.6% | 98.54% | 0.13 | -4.65 | 109 | signal_flip:64, stop_loss_pct:44, end_of_data:1 |  |
| `example_sma_cross` | SOL-USDT-SWAP | 15m | ok | 8640 | -9,839.52 | -98.40% | 24.2% | 99.83% | 0.11 | -4.34 | 376 | signal_flip:308, stop_loss_pct:67, end_of_data:1 |  |
| `example_sma_cross` | SOL-USDT-SWAP | 1H | ok | 2160 | -8,706.50 | -87.06% | 21.8% | 89.18% | 0.20 | -8.10 | 87 | signal_flip:58, stop_loss_pct:28, end_of_data:1 |  |
| `ict_liquidity_fvg` | BTC-USDT-SWAP | 15m | ok | 8640 | -717.26 | -7.17% | 28.6% | 7.40% | 0.33 | -7.31 | 49 | sl:28, tp:11, stop_loss_pct:6 |  |
| `ict_liquidity_fvg` | BTC-USDT-SWAP | 1H | ok | 2160 | -165.85 | -1.66% | 16.7% | 3.25% | 0.63 | -2.99 | 12 | sl:6, stop_loss_pct:3, tp:2 |  |
| `ict_liquidity_fvg` | ETH-USDT-SWAP | 15m | ok | 8640 | -1,066.54 | -10.67% | 32.4% | 13.99% | 0.44 | -4.99 | 71 | sl:29, tp:18, stop_loss_pct:15 |  |
| `ict_liquidity_fvg` | ETH-USDT-SWAP | 1H | ok | 2160 | -483.45 | -4.83% | 31.2% | 7.18% | 0.46 | -4.61 | 16 | stop_loss_pct:9, tp:4, sl:2 |  |
| `ict_liquidity_fvg` | SOL-USDT-SWAP | 15m | ok | 8640 | -358.55 | -3.59% | 36.7% | 4.81% | 0.67 | -2.66 | 49 | sl:22, tp:15, stop_loss_pct:8 |  |
| `ict_liquidity_fvg` | SOL-USDT-SWAP | 1H | ok | 2160 | -551.72 | -5.52% | 14.3% | 5.59% | 0.15 | -14.29 | 14 | sl:7, stop_loss_pct:5, signal_flip:1 |  |
| `livermore` | BTC-USDT-SWAP | 15m | ok | 8640 | -8,565.19 | -85.65% | 24.4% | 88.82% | 0.31 | -5.63 | 176 | signal:171, stop_loss_pct:5 |  |
| `livermore` | BTC-USDT-SWAP | 1H | ok | 2160 | -5,251.70 | -52.52% | 28.0% | 55.88% | 0.30 | -6.64 | 50 | signal:43, stop_loss_pct:7 |  |
| `livermore` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,766.91 | -97.67% | 22.7% | 99.38% | 0.21 | -5.40 | 211 | signal:150, stop_loss_pct:61 |  |
| `livermore` | ETH-USDT-SWAP | 1H | ok | 2160 | -7,572.27 | -75.72% | 18.9% | 83.23% | 0.43 | -2.96 | 53 | signal:28, stop_loss_pct:25 |  |
| `livermore` | SOL-USDT-SWAP | 15m | ok | 8640 | -8,707.01 | -87.07% | 26.9% | 89.22% | 0.19 | -6.67 | 156 | signal:135, stop_loss_pct:21 |  |
| `livermore` | SOL-USDT-SWAP | 1H | ok | 2160 | -5,941.50 | -59.42% | 25.5% | 60.82% | 0.26 | -7.78 | 51 | signal:42, stop_loss_pct:9 |  |
| `ma_7d_5m` | BTC-USDT-SWAP | 15m | ok | 8640 | 563.49 | 5.63% | 50.0% | 3.51% | 2.26 | 4.66 | 10 | signal:7, tp:3 |  |
| `ma_7d_5m` | BTC-USDT-SWAP | 1H | ok | 2160 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0.00 | 0 | - |  |
| `ma_7d_5m` | ETH-USDT-SWAP | 15m | ok | 8640 | -4,014.78 | -40.15% | 35.7% | 41.98% | 0.27 | -8.53 | 14 | signal:7, stop_loss_pct:5, tp:2 |  |
| `ma_7d_5m` | ETH-USDT-SWAP | 1H | ok | 2160 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0.00 | 0 | - |  |
| `ma_7d_5m` | SOL-USDT-SWAP | 15m | ok | 8640 | 186.97 | 1.87% | 41.7% | 4.11% | 1.31 | 1.67 | 12 | signal:9, tp:3 |  |
| `ma_7d_5m` | SOL-USDT-SWAP | 1H | ok | 2160 | 0.00 | 0.00% | 0.0% | 0.00% | 0.00 | 0.00 | 0 | - |  |
| `macd_strategy` | BTC-USDT-SWAP | 15m | ok | 8640 | -9,294.12 | -92.94% | 27.5% | 97.91% | 0.38 | -3.13 | 528 | signal_flip:515, stop_loss_pct:12, end_of_data:1 |  |
| `macd_strategy` | BTC-USDT-SWAP | 1H | ok | 2160 | -6,252.92 | -62.53% | 30.9% | 66.50% | 0.61 | -2.78 | 136 | signal_flip:122, stop_loss_pct:14 |  |
| `macd_strategy` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,718.11 | -97.18% | 24.6% | 99.96% | 0.32 | -3.04 | 553 | signal_flip:472, stop_loss_pct:80, end_of_data:1 |  |
| `macd_strategy` | ETH-USDT-SWAP | 1H | ok | 2160 | -9,202.58 | -92.03% | 25.9% | 97.24% | 0.21 | -6.01 | 135 | signal_flip:80, stop_loss_pct:54, end_of_data:1 |  |
| `macd_strategy` | SOL-USDT-SWAP | 15m | ok | 8640 | -9,878.34 | -98.78% | 24.3% | 100.00% | 0.09 | -3.00 | 610 | signal_flip:528, stop_loss_pct:81, end_of_data:1 |  |
| `macd_strategy` | SOL-USDT-SWAP | 1H | ok | 2160 | -9,272.60 | -92.73% | 27.8% | 94.60% | 0.19 | -6.57 | 126 | signal_flip:87, stop_loss_pct:38, end_of_data:1 |  |
| `mean_reversion` | BTC-USDT-SWAP | 15m | ok | 8640 | 19,399.84 | 194.00% | 66.9% | 28.48% | 1.49 | 2.12 | 290 | signal:257, signal_flip:16, stop_loss_pct:16 |  |
| `mean_reversion` | BTC-USDT-SWAP | 1H | ok | 2160 | -465.67 | -4.66% | 59.4% | 33.21% | 0.96 | -0.25 | 69 | signal:51, stop_loss_pct:15, signal_flip:3 |  |
| `mean_reversion` | ETH-USDT-SWAP | 15m | ok | 8640 | 11,994.74 | 119.95% | 64.2% | 41.88% | 1.20 | 0.96 | 282 | signal:210, stop_loss_pct:53, signal_flip:18 |  |
| `mean_reversion` | ETH-USDT-SWAP | 1H | ok | 2160 | 76,217.49 | 762.17% | 62.2% | 22.58% | 2.45 | 3.86 | 74 | signal:44, stop_loss_pct:24, signal_flip:6 |  |
| `mean_reversion` | SOL-USDT-SWAP | 15m | ok | 8640 | 38,399.67 | 384.00% | 56.6% | 80.63% | 1.11 | 0.29 | 304 | signal:247, stop_loss_pct:38, signal_flip:18 |  |
| `mean_reversion` | SOL-USDT-SWAP | 1H | ok | 2160 | 5,841.46 | 58.41% | 60.6% | 29.71% | 1.26 | 1.44 | 71 | signal:46, stop_loss_pct:21, signal_flip:4 |  |
| `multi_ema` | BTC-USDT-SWAP | 15m | ok | 8640 | -8,972.73 | -89.73% | 21.6% | 94.21% | 0.32 | -4.46 | 310 | signal:303, stop_loss_pct:6, end_of_data:1 |  |
| `multi_ema` | BTC-USDT-SWAP | 1H | ok | 2160 | -5,212.65 | -52.13% | 27.3% | 58.04% | 0.47 | -4.37 | 77 | signal:72, stop_loss_pct:4, end_of_data:1 |  |
| `multi_ema` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,791.73 | -97.92% | 18.0% | 99.85% | 0.17 | -4.58 | 328 | signal:275, stop_loss_pct:52, end_of_data:1 |  |
| `multi_ema` | ETH-USDT-SWAP | 1H | ok | 2160 | -9,509.75 | -95.10% | 10.2% | 96.43% | 0.07 | -10.07 | 88 | signal:53, stop_loss_pct:34, end_of_data:1 |  |
| `multi_ema` | SOL-USDT-SWAP | 15m | ok | 8640 | -9,880.18 | -98.80% | 16.8% | 99.93% | 0.03 | -4.39 | 334 | signal:282, stop_loss_pct:51, end_of_data:1 |  |
| `multi_ema` | SOL-USDT-SWAP | 1H | ok | 2160 | -8,979.00 | -89.79% | 12.3% | 91.44% | 0.08 | -9.41 | 81 | signal:61, stop_loss_pct:20 |  |
| `multi_factor` | BTC-USDT-SWAP | 15m | ok | 8640 | 199.76 | 2.00% | 41.9% | 26.53% | 1.02 | 0.08 | 258 | signal:258 |  |
| `multi_factor` | BTC-USDT-SWAP | 1H | ok | 2160 | -833.86 | -8.34% | 39.4% | 16.81% | 0.87 | -0.76 | 66 | signal:64, end_of_data:1, stop_loss_pct:1 |  |
| `multi_factor` | ETH-USDT-SWAP | 15m | ok | 8640 | -6,628.94 | -66.29% | 42.8% | 75.15% | 0.62 | -2.20 | 243 | signal:218, stop_loss_pct:25 |  |
| `multi_factor` | ETH-USDT-SWAP | 1H | ok | 2160 | -4,307.96 | -43.08% | 41.4% | 50.68% | 0.50 | -4.09 | 58 | signal:47, stop_loss_pct:11 |  |
| `multi_factor` | SOL-USDT-SWAP | 15m | ok | 8640 | -834.23 | -8.34% | 40.1% | 48.74% | 0.97 | -0.14 | 272 | signal:266, stop_loss_pct:6 |  |
| `multi_factor` | SOL-USDT-SWAP | 1H | ok | 2160 | -3,000.53 | -30.01% | 32.2% | 33.43% | 0.61 | -2.84 | 59 | signal:52, stop_loss_pct:6, end_of_data:1 |  |
| `rsi_bollinger_combo` | BTC-USDT-SWAP | 15m | ok | 8640 | 19,023.95 | 190.24% | 68.5% | 17.63% | 1.73 | 2.90 | 267 | signal:251, stop_loss_pct:9, signal_flip:6 |  |
| `rsi_bollinger_combo` | BTC-USDT-SWAP | 1H | ok | 2160 | -2,295.92 | -22.96% | 61.3% | 44.90% | 0.79 | -1.42 | 62 | signal:43, stop_loss_pct:16, signal_flip:3 |  |
| `rsi_bollinger_combo` | ETH-USDT-SWAP | 15m | ok | 8640 | 26,847.07 | 268.47% | 67.2% | 46.03% | 1.32 | 1.37 | 256 | signal:206, stop_loss_pct:40, signal_flip:10 |  |
| `rsi_bollinger_combo` | ETH-USDT-SWAP | 1H | ok | 2160 | 92,250.05 | 922.50% | 60.9% | 18.40% | 2.23 | 3.41 | 64 | signal:39, stop_loss_pct:20, signal_flip:5 |  |
| `rsi_bollinger_combo` | SOL-USDT-SWAP | 15m | ok | 8640 | 10,242.23 | 102.42% | 58.8% | 45.48% | 1.20 | 0.99 | 228 | signal:196, stop_loss_pct:26, signal_flip:6 |  |
| `rsi_bollinger_combo` | SOL-USDT-SWAP | 1H | ok | 2160 | 14,549.03 | 145.49% | 68.1% | 13.21% | 1.70 | 3.36 | 69 | signal:52, stop_loss_pct:14, signal_flip:3 |  |
| `rsi_bollinger_regime` | BTC-USDT-SWAP | 15m | ok | 8640 | 4,251.68 | 42.52% | 58.5% | 18.39% | 1.51 | 2.39 | 147 | signal:146, end_of_data:1 |  |
| `rsi_bollinger_regime` | BTC-USDT-SWAP | 1H | ok | 2160 | -749.77 | -7.50% | 44.4% | 17.29% | 0.75 | -1.67 | 36 | signal:35, stop_loss_pct:1 |  |
| `rsi_bollinger_regime` | ETH-USDT-SWAP | 15m | ok | 8640 | 2,306.69 | 23.07% | 58.5% | 38.97% | 1.11 | 0.48 | 147 | signal:138, stop_loss_pct:9 |  |
| `rsi_bollinger_regime` | ETH-USDT-SWAP | 1H | ok | 2160 | 4,697.19 | 46.97% | 45.7% | 68.49% | 1.37 | 1.23 | 35 | signal:30, stop_loss_pct:5 |  |
| `rsi_bollinger_regime` | SOL-USDT-SWAP | 15m | ok | 8640 | 9,842.72 | 98.43% | 45.6% | 29.02% | 1.45 | 1.83 | 125 | signal:122, stop_loss_pct:2, signal_flip:1 |  |
| `rsi_bollinger_regime` | SOL-USDT-SWAP | 1H | ok | 2160 | 5,482.70 | 54.83% | 62.5% | 14.34% | 1.89 | 3.76 | 40 | signal:38, signal_flip:1, stop_loss_pct:1 |  |
| `volume_momentum` | BTC-USDT-SWAP | 15m | ok | 8640 | -6,470.85 | -64.71% | 18.8% | 66.64% | 0.17 | -9.47 | 64 | signal:60, stop_loss_pct:4 |  |
| `volume_momentum` | BTC-USDT-SWAP | 1H | ok | 2160 | -3,318.89 | -33.19% | 36.0% | 40.36% | 0.46 | -4.13 | 50 | signal:43, stop_loss_pct:7 |  |
| `volume_momentum` | ETH-USDT-SWAP | 15m | ok | 8640 | -9,881.70 | -98.82% | 15.4% | 99.94% | 0.09 | -3.39 | 188 | signal:104, stop_loss_pct:84 |  |
| `volume_momentum` | ETH-USDT-SWAP | 1H | ok | 2160 | -9,461.57 | -94.62% | 20.4% | 96.08% | 0.26 | -5.85 | 98 | signal:50, stop_loss_pct:48 |  |
| `volume_momentum` | SOL-USDT-SWAP | 15m | ok | 8640 | -9,482.51 | -94.83% | 20.5% | 96.23% | 0.13 | -7.53 | 127 | signal:93, stop_loss_pct:34 |  |
| `volume_momentum` | SOL-USDT-SWAP | 1H | ok | 2160 | -8,182.88 | -81.83% | 19.7% | 83.23% | 0.08 | -10.18 | 76 | signal:56, stop_loss_pct:20 |  |

## 검증 메모

- 총 실행 행: `96`
- 정상 실행 행: `96`
- 데이터부족/오류 행: `0`
- 원자료 JSON: `.omx/context/all-strategy-backtest-comparison-20260508.json`
