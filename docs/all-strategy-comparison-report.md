# 전체 전략 백테스트 비교 리포트

- 작성일: 2026-04-26
- 기간: `2026-03-01` ~ `2026-04-25`
- 종목: `BTC-USDT-SWAP`, `ETH-USDT-SWAP`, `SOL-USDT-SWAP`
- 시간봉: `15m`, `1H`
- 비용: 수수료 `0.05%`, 슬리피지 `0.05%`, 펀딩 `0.01%/8h`, 유동성 영향 `0.1`
- 실행 후보: `16`개, 완료 run: `96`개, 에러: `0`개
- 참고: `chronos_regime_hybrid` 기본 ML 프로필은 15m run에서 장시간 응답하지 않아, 비교표에는 `chronos_enabled=false` fallback 프로필을 사용했습니다.

## 결론

단순 합산 PnL 1위는 **`example_rsi`** 입니다. 합산 PnL `223695.86`, 양수 run `3/6`, 평균 PF `1.08`, 최대 DD `47.76%`였습니다. 하지만 ETH 성과 편중과 큰 낙폭 때문에 보수적 1순위로 보기는 어렵습니다.

단, 이 비교는 기본 파라미터 중심의 55일 샘플입니다. 바로 실거래할 수준의 검증은 아니며, 상위 후보만 다음 단계의 장기/워크포워드 검증으로 넘겨야 합니다.

보수적으로 보면 **실거래 합격 전략은 아직 0개**입니다. 수익 상위 전략들도 최대 낙폭이 `25%~48%` 수준이라 리스크가 너무 큽니다. 따라서 현재 결과는 “바로 쓸 전략”이 아니라 “장기 검증으로 넘길 후보군”을 고른 것으로 봐야 합니다.

## 보수적 후보군

| 구분 | 전략 | 이유 | 주요 리스크 |
|---|---|---|---|
| 1차 연구 후보 | `rsi_bollinger_regime` | 합산 PnL 양수, PF 양호, 상위권 중 DD가 상대적으로 낮음 | SOL/BTC 1H 약함, Max DD 25% 이상 |
| 1차 연구 후보 | `rsi_bollinger_combo` | 6개 중 4개 run 양수, 수익성 강함 | BTC 1H/SOL 15m 손실, Max DD 42% 이상 |
| 1차 연구 후보 | `mean_reversion` | ETH/BTC 15m과 ETH 1H에서 강함 | SOL 약함, DD 높음 |
| 참고 후보 | `example_rsi` | 수익률 1위 | ETH 편중이 심하고 DD/분산이 큼 |
| 보류 | `ict_liquidity_fvg` | 낮은 DD | 합산 PnL 음수, 엣지 부족 |

## 종합 순위

| 순위 | 후보 | 판정 | 합산 PnL | 양수 Run | 거래수 | 평균 PF | 평균 Sharpe | 평균 승률 | Max DD | 최고 Run | 최악 Run |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | `example_rsi` | 관찰 | 223695.86 | 3/6 | 1417 | 1.08 | -0.51 | 46.7% | 47.76% | ETH-USDT-SWAP 15m 175697.48 | SOL-USDT-SWAP 15m -4040.03 |
| 2 | `rsi_bollinger_combo` | 관찰 | 79971.04 | 4/6 | 499 | 1.38 | 0.79 | 63.3% | 42.76% | ETH-USDT-SWAP 1H 58151.93 | BTC-USDT-SWAP 1H -2946.05 |
| 3 | `mean_reversion` | 관찰 | 63787.88 | 3/6 | 559 | 1.26 | 0.32 | 62.5% | 40.84% | ETH-USDT-SWAP 1H 44441.99 | BTC-USDT-SWAP 1H -2545.36 |
| 4 | `rsi_bollinger_regime` | 관찰 | 39922.12 | 3/6 | 298 | 1.32 | -0.11 | 48.9% | 25.24% | ETH-USDT-SWAP 1H 31513.24 | BTC-USDT-SWAP 1H -1319.29 |
| 5 | `bollinger_band` | 관찰 | 32109.17 | 4/6 | 410 | 1.15 | 0.46 | 59.7% | 43.99% | BTC-USDT-SWAP 15m 17233.84 | SOL-USDT-SWAP 15m -1556.39 |
| 6 | `chronos_regime_hybrid__fallback_no_chronos` | 관찰 | 22320.87 | 3/6 | 287 | 1.36 | -0.00 | 52.7% | 29.87% | ETH-USDT-SWAP 1H 17761.09 | BTC-USDT-SWAP 1H -1501.07 |
| 7 | `elliott_wave_fib` | 관찰 | 6146.23 | 3/6 | 132 | 1.07 | -0.25 | 48.1% | 46.05% | ETH-USDT-SWAP 1H 7098.38 | BTC-USDT-SWAP 1H -1656.52 |
| 8 | `ict_liquidity_fvg__session_rr1_5` | 탈락 | -498.15 | 1/6 | 83 | 0.84 | -1.56 | 37.3% | 6.97% | SOL-USDT-SWAP 15m 89.28 | ETH-USDT-SWAP 15m -279.08 |
| 9 | `ict_liquidity_fvg` | 탈락 | -1124.17 | 1/6 | 115 | 0.67 | -3.19 | 33.4% | 7.44% | SOL-USDT-SWAP 15m 17.15 | ETH-USDT-SWAP 15m -468.79 |
| 10 | `multi_factor` | 부분관찰 | -8482.42 | 2/6 | 486 | 0.84 | -1.20 | 40.0% | 61.20% | BTC-USDT-SWAP 1H 782.13 | ETH-USDT-SWAP 15m -5705.18 |
| 11 | `livermore` | 탈락 | -30570.56 | 0/6 | 373 | 0.35 | -6.88 | 28.4% | 96.01% | SOL-USDT-SWAP 15m -1400.73 | ETH-USDT-SWAP 15m -9446.92 |
| 12 | `volume_momentum` | 탈락 | -32037.55 | 0/6 | 315 | 0.26 | -8.39 | 23.8% | 98.35% | SOL-USDT-SWAP 15m -379.71 | ETH-USDT-SWAP 15m -9723.34 |
| 13 | `example_sma_cross` | 탈락 | -37089.85 | 0/6 | 705 | 0.44 | -4.23 | 23.7% | 98.22% | SOL-USDT-SWAP 15m -528.43 | ETH-USDT-SWAP 15m -9526.99 |
| 14 | `multi_ema` | 탈락 | -37328.34 | 0/6 | 597 | 0.33 | -5.65 | 20.0% | 98.36% | SOL-USDT-SWAP 15m -1990.48 | ETH-USDT-SWAP 15m -9679.26 |
| 15 | `breakout_strategy` | 탈락 | -37628.79 | 0/6 | 358 | 0.27 | -8.11 | 23.6% | 97.03% | SOL-USDT-SWAP 15m -1318.52 | ETH-USDT-SWAP 15m -9535.88 |
| 16 | `macd_strategy` | 탈락 | -39091.51 | 0/6 | 1062 | 0.44 | -3.39 | 29.8% | 99.53% | SOL-USDT-SWAP 15m -3462.64 | ETH-USDT-SWAP 15m -9778.38 |

## 상위 후보 해석

- `example_rsi`: 판정 **관찰**. 합산 PnL `223695.86`, 양수 run `3/6`, 거래수 `1417`. 최고 run은 `ETH-USDT-SWAP 15m` `175697.48`, 최악 run은 `SOL-USDT-SWAP 15m` `-4040.03`.
- `rsi_bollinger_combo`: 판정 **관찰**. 합산 PnL `79971.04`, 양수 run `4/6`, 거래수 `499`. 최고 run은 `ETH-USDT-SWAP 1H` `58151.93`, 최악 run은 `BTC-USDT-SWAP 1H` `-2946.05`.
- `mean_reversion`: 판정 **관찰**. 합산 PnL `63787.88`, 양수 run `3/6`, 거래수 `559`. 최고 run은 `ETH-USDT-SWAP 1H` `44441.99`, 최악 run은 `BTC-USDT-SWAP 1H` `-2545.36`.
- `rsi_bollinger_regime`: 판정 **관찰**. 합산 PnL `39922.12`, 양수 run `3/6`, 거래수 `298`. 최고 run은 `ETH-USDT-SWAP 1H` `31513.24`, 최악 run은 `BTC-USDT-SWAP 1H` `-1319.29`.
- `bollinger_band`: 판정 **관찰**. 합산 PnL `32109.17`, 양수 run `4/6`, 거래수 `410`. 최고 run은 `BTC-USDT-SWAP 15m` `17233.84`, 최악 run은 `SOL-USDT-SWAP 15m` `-1556.39`.

## Run 상세

| 후보 | 종목 | TF | PnL | 수익률 | 승률 | Max DD | PF | Sharpe | 거래수 | Run ID |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `bollinger_band` | BTC-USDT-SWAP | 15m | 17233.84 | 172.34% | 74.5% | 23.94% | 1.57 | 2.69 | 137 | `265db088-9192-41dc-a8f1-1fcdfb3f1eee` |
| `bollinger_band` | BTC-USDT-SWAP | 1H | -1473.28 | -14.73% | 51.6% | 25.88% | 0.80 | -1.51 | 31 | `abbcfa36-f118-4041-8495-3c97cd7f6745` |
| `bollinger_band` | ETH-USDT-SWAP | 15m | 1469.25 | 14.69% | 60.2% | 43.99% | 1.05 | 0.30 | 123 | `bf8843ee-4bc5-4949-8197-5ed387a10307` |
| `bollinger_band` | ETH-USDT-SWAP | 1H | 16391.42 | 163.91% | 51.4% | 23.99% | 1.74 | 2.91 | 35 | `776da60f-a626-4a9e-a67f-4a222a48c567` |
| `bollinger_band` | SOL-USDT-SWAP | 15m | -1556.39 | -15.56% | 62.7% | 36.69% | 0.75 | -1.68 | 51 | `d292916a-d6bb-45f1-8431-b51a8b705a72` |
| `bollinger_band` | SOL-USDT-SWAP | 1H | 44.33 | 0.44% | 57.6% | 24.53% | 1.01 | 0.04 | 33 | `6fdaf711-213c-43d8-9545-148d96275370` |
| `breakout_strategy` | BTC-USDT-SWAP | 15m | -7984.71 | -79.85% | 22.5% | 81.84% | 0.24 | -7.06 | 102 | `8f0ac868-fb2a-4a90-96d8-c0aa0c120686` |
| `breakout_strategy` | BTC-USDT-SWAP | 1H | -5994.84 | -59.95% | 22.9% | 61.03% | 0.15 | -11.53 | 35 | `943eab92-3fcb-4938-8f00-2b1bdc68b4d5` |
| `breakout_strategy` | ETH-USDT-SWAP | 15m | -9535.88 | -95.36% | 16.5% | 97.03% | 0.05 | -8.87 | 115 | `d737a58f-59fd-4862-99c4-1042b297bd2e` |
| `breakout_strategy` | ETH-USDT-SWAP | 1H | -7348.44 | -73.48% | 23.1% | 74.64% | 0.07 | -12.59 | 26 | `51b2ead0-1a7a-40b8-9081-662baba71fb8` |
| `breakout_strategy` | SOL-USDT-SWAP | 15m | -1318.52 | -13.19% | 38.3% | 23.65% | 0.79 | -1.49 | 47 | `0716729c-0676-42a5-abe5-8e79627b1ed4` |
| `breakout_strategy` | SOL-USDT-SWAP | 1H | -5446.39 | -54.46% | 18.2% | 55.53% | 0.33 | -7.12 | 33 | `74758257-b957-4c98-a4da-2795d5b371bf` |
| `chronos_regime_hybrid__fallback_no_chronos` | BTC-USDT-SWAP | 15m | 3579.50 | 35.80% | 63.4% | 9.66% | 1.78 | 3.36 | 93 | `bdefe36b-4b21-4d92-93f1-e306b26553cb` |
| `chronos_regime_hybrid__fallback_no_chronos` | BTC-USDT-SWAP | 1H | -1501.07 | -15.01% | 42.9% | 19.37% | 0.42 | -5.29 | 21 | `65c98c9b-a4e8-4640-bf1f-c63e97947098` |
| `chronos_regime_hybrid__fallback_no_chronos` | ETH-USDT-SWAP | 15m | 3876.67 | 38.77% | 55.1% | 29.87% | 1.25 | 1.05 | 98 | `43ff869b-539e-4def-9421-3d748589d7e1` |
| `chronos_regime_hybrid__fallback_no_chronos` | ETH-USDT-SWAP | 1H | 17761.09 | 177.61% | 60.0% | 15.43% | 3.20 | 4.64 | 20 | `386f2517-a007-4835-90ac-5665a1cbb6ae` |
| `chronos_regime_hybrid__fallback_no_chronos` | SOL-USDT-SWAP | 15m | -393.21 | -3.93% | 44.8% | 11.23% | 0.76 | -1.73 | 29 | `36c4d173-e588-4a32-a170-392e95ffd587` |
| `chronos_regime_hybrid__fallback_no_chronos` | SOL-USDT-SWAP | 1H | -1002.11 | -10.02% | 50.0% | 13.03% | 0.72 | -2.04 | 26 | `55042f1f-3993-40aa-b52b-881cd5e57ab8` |
| `elliott_wave_fib` | BTC-USDT-SWAP | 15m | 267.33 | 2.67% | 51.5% | 21.63% | 1.04 | 0.27 | 33 | `686e4a06-1968-4dfd-a53b-fa459f3831d8` |
| `elliott_wave_fib` | BTC-USDT-SWAP | 1H | -1656.52 | -16.57% | 44.4% | 21.55% | 0.67 | -2.59 | 18 | `65605f65-09d0-433d-af63-55ac30c4fafb` |
| `elliott_wave_fib` | ETH-USDT-SWAP | 15m | -1529.03 | -15.29% | 42.9% | 46.05% | 0.88 | -0.79 | 42 | `1b60f796-1fab-4cab-9f56-63afc23f6db4` |
| `elliott_wave_fib` | ETH-USDT-SWAP | 1H | 7098.38 | 70.98% | 42.9% | 24.08% | 1.72 | 3.40 | 21 | `80cd5896-00ae-47b8-a7ba-0dca4c024d62` |
| `elliott_wave_fib` | SOL-USDT-SWAP | 15m | -696.09 | -6.96% | 50.0% | 7.15% | 0.44 | -5.27 | 4 | `11f505d1-02bf-4269-bbb3-a19a0c1ec629` |
| `elliott_wave_fib` | SOL-USDT-SWAP | 1H | 2662.16 | 26.62% | 57.1% | 12.62% | 1.70 | 3.47 | 14 | `9197d897-bc70-4d8c-a168-ed31ebc81352` |
| `example_rsi` | BTC-USDT-SWAP | 15m | 1872.40 | 18.72% | 48.7% | 38.69% | 1.07 | 0.39 | 452 | `046e0b33-7af1-494a-81bf-b374ec39686e` |
| `example_rsi` | BTC-USDT-SWAP | 1H | -2304.92 | -23.05% | 47.8% | 32.89% | 0.75 | -1.74 | 115 | `7ebdba66-d4cf-4e66-aa18-d1bbd2b55c83` |
| `example_rsi` | ETH-USDT-SWAP | 15m | 175697.48 | 1756.97% | 50.6% | 39.91% | 1.51 | 1.79 | 468 | `6afe1683-7f28-4c42-971f-9747ff44e583` |
| `example_rsi` | ETH-USDT-SWAP | 1H | 54704.17 | 547.04% | 50.8% | 22.70% | 1.98 | 3.44 | 120 | `1d596a33-32a6-4391-8472-b8e32b8f0ca0` |
| `example_rsi` | SOL-USDT-SWAP | 15m | -4040.03 | -40.40% | 37.2% | 47.76% | 0.47 | -4.92 | 164 | `698e2f03-af27-4b81-a186-a7e9c5dfa458` |
| `example_rsi` | SOL-USDT-SWAP | 1H | -2233.25 | -22.33% | 44.9% | 34.43% | 0.72 | -2.01 | 98 | `7e61dfe3-6852-4b0d-8728-f700dd79cdf2` |
| `example_sma_cross` | BTC-USDT-SWAP | 15m | -7788.03 | -77.88% | 23.0% | 83.27% | 0.39 | -4.06 | 230 | `87ba4783-7166-48c9-8856-99e93ff56e0c` |
| `example_sma_cross` | BTC-USDT-SWAP | 1H | -4524.94 | -45.25% | 28.8% | 57.14% | 0.50 | -3.96 | 52 | `6a49cec4-8440-4962-8d49-289c5a915ef4` |
| `example_sma_cross` | ETH-USDT-SWAP | 15m | -9526.99 | -95.27% | 20.9% | 98.22% | 0.31 | -3.04 | 230 | `a9e8c946-d6f0-490c-8241-13ba09130663` |
| `example_sma_cross` | ETH-USDT-SWAP | 1H | -9003.62 | -90.04% | 14.9% | 91.04% | 0.08 | -8.78 | 67 | `2637f246-d129-427b-931a-7dfe37cfa85e` |
| `example_sma_cross` | SOL-USDT-SWAP | 15m | -528.43 | -5.28% | 26.6% | 15.28% | 0.93 | -0.41 | 79 | `a8b3559a-d7c6-4697-bf29-ad2234d65676` |
| `example_sma_cross` | SOL-USDT-SWAP | 1H | -5717.83 | -57.18% | 27.7% | 58.83% | 0.42 | -5.14 | 47 | `fa9ef395-7ffd-41b9-86f4-9d4e65fa2058` |
| `ict_liquidity_fvg` | BTC-USDT-SWAP | 15m | -289.47 | -2.89% | 34.4% | 3.81% | 0.53 | -4.13 | 32 | `ec981eeb-cf27-48fa-b27b-2fe75faa45bd` |
| `ict_liquidity_fvg` | BTC-USDT-SWAP | 1H | -173.02 | -1.73% | 11.1% | 3.25% | 0.47 | -4.56 | 9 | `2f46566e-4a4a-4c95-a5cb-53c4c451bb1d` |
| `ict_liquidity_fvg` | ETH-USDT-SWAP | 15m | -468.79 | -4.69% | 34.9% | 7.44% | 0.59 | -3.48 | 43 | `ab710a4f-20f8-4956-9a37-bd0faad0efd2` |
| `ict_liquidity_fvg` | ETH-USDT-SWAP | 1H | -0.68 | -0.01% | 41.7% | 3.06% | 1.00 | -0.01 | 12 | `9153d935-631e-44db-ac91-1055ea10f469` |
| `ict_liquidity_fvg` | SOL-USDT-SWAP | 15m | 17.15 | 0.17% | 50.0% | 0.65% | 1.11 | 0.70 | 12 | `e9bd8726-0500-4491-8e9f-c243ebb31d59` |
| `ict_liquidity_fvg` | SOL-USDT-SWAP | 1H | -209.39 | -2.09% | 28.6% | 2.13% | 0.32 | -7.68 | 7 | `41274b93-8cba-4e51-bf0c-a5dbf062242d` |
| `ict_liquidity_fvg__session_rr1_5` | BTC-USDT-SWAP | 15m | -80.24 | -0.80% | 47.6% | 1.52% | 0.75 | -1.89 | 21 | `74e94cea-8466-47d3-9e5b-a434c2c5720d` |
| `ict_liquidity_fvg__session_rr1_5` | BTC-USDT-SWAP | 1H | -114.51 | -1.15% | 16.7% | 2.29% | 0.50 | -4.46 | 6 | `3bf3b2e7-4a09-4c10-a9d7-1728be919b78` |
| `ict_liquidity_fvg__session_rr1_5` | ETH-USDT-SWAP | 15m | -279.08 | -2.79% | 36.4% | 6.97% | 0.68 | -2.44 | 33 | `9b7b87fb-d77d-4122-83f7-3529a816ee77` |
| `ict_liquidity_fvg__session_rr1_5` | ETH-USDT-SWAP | 1H | -99.90 | -1.00% | 28.6% | 2.46% | 0.66 | -2.73 | 7 | `8ab80ee0-e2f1-4c87-b0c0-a3dae0bbc011` |
| `ict_liquidity_fvg__session_rr1_5` | SOL-USDT-SWAP | 15m | 89.28 | 0.89% | 61.5% | 0.65% | 1.67 | 3.55 | 13 | `3b31ec0c-a9b2-4099-b076-e02b36b3c094` |
| `ict_liquidity_fvg__session_rr1_5` | SOL-USDT-SWAP | 1H | -13.71 | -0.14% | 33.3% | 0.70% | 0.80 | -1.39 | 3 | `f08c99b6-9b8a-44cc-82b9-17fbd2f0ad8a` |
| `livermore` | BTC-USDT-SWAP | 15m | -7494.05 | -74.94% | 22.0% | 77.40% | 0.21 | -7.01 | 109 | `ad5221ac-01f3-42f4-add9-c56f8ede4e5c` |
| `livermore` | BTC-USDT-SWAP | 1H | -2988.36 | -29.88% | 35.5% | 38.81% | 0.43 | -4.77 | 31 | `0ad92d86-cf8a-4815-bf12-25b304ceed69` |
| `livermore` | ETH-USDT-SWAP | 15m | -9446.92 | -94.47% | 21.5% | 96.01% | 0.17 | -6.85 | 121 | `567fbc08-f15c-4c28-b3a5-e51ad1a31972` |
| `livermore` | ETH-USDT-SWAP | 1H | -6661.45 | -66.61% | 16.7% | 67.72% | 0.04 | -16.55 | 30 | `17f51c0b-1c6e-49cc-8bc4-3d3f4a3aa61e` |
| `livermore` | SOL-USDT-SWAP | 15m | -1400.73 | -14.01% | 39.6% | 17.92% | 0.71 | -2.27 | 48 | `dc13acf7-c9d8-4e90-bc54-82c968e2239d` |
| `livermore` | SOL-USDT-SWAP | 1H | -2579.05 | -25.79% | 35.3% | 30.48% | 0.52 | -3.83 | 34 | `0599d747-c759-4527-80aa-bc92f1ba1f7c` |
| `macd_strategy` | BTC-USDT-SWAP | 15m | -8822.14 | -88.22% | 26.4% | 93.53% | 0.34 | -3.48 | 337 | `801de0b6-2c71-4af7-8af9-154ae8be9307` |
| `macd_strategy` | BTC-USDT-SWAP | 1H | -4647.09 | -46.47% | 29.1% | 64.23% | 0.59 | -2.86 | 86 | `f72e1cd7-d2bb-4cf9-aa07-176134ccbc96` |
| `macd_strategy` | ETH-USDT-SWAP | 15m | -9778.38 | -97.78% | 23.3% | 99.53% | 0.20 | -3.05 | 348 | `0bd5f013-8d0a-4f73-87d2-3e1d6693cb0a` |
| `macd_strategy` | ETH-USDT-SWAP | 1H | -5973.29 | -59.73% | 29.3% | 85.15% | 0.45 | -4.61 | 75 | `ca41fba6-e250-45b7-b415-4858baeaae3e` |
| `macd_strategy` | SOL-USDT-SWAP | 15m | -3462.64 | -34.63% | 31.9% | 40.36% | 0.65 | -2.50 | 144 | `8264c06a-865a-4e8c-b005-a61cef540a2e` |
| `macd_strategy` | SOL-USDT-SWAP | 1H | -6407.97 | -64.08% | 38.9% | 74.32% | 0.40 | -3.84 | 72 | `9a3796ad-333c-41b9-be3e-0a4605fead70` |
| `mean_reversion` | BTC-USDT-SWAP | 15m | 10198.82 | 101.99% | 68.5% | 22.49% | 1.58 | 2.44 | 178 | `7d768e17-434f-4b8c-bd6d-c735d4cfedb9` |
| `mean_reversion` | BTC-USDT-SWAP | 1H | -2545.36 | -25.45% | 54.8% | 33.21% | 0.68 | -2.43 | 42 | `9c37528b-1a8a-4b17-a734-470efddef9d5` |
| `mean_reversion` | ETH-USDT-SWAP | 15m | 15282.49 | 152.82% | 64.9% | 40.84% | 1.31 | 1.48 | 174 | `05d01359-27ea-465f-9b4b-77af2d4ace46` |
| `mean_reversion` | ETH-USDT-SWAP | 1H | 44441.99 | 444.42% | 63.8% | 22.58% | 2.61 | 4.35 | 47 | `79e36928-cace-4aa3-84ca-f7f216e8145c` |
| `mean_reversion` | SOL-USDT-SWAP | 15m | -2251.12 | -22.51% | 62.7% | 31.82% | 0.57 | -2.67 | 75 | `587505d6-0f03-4a4f-ab1c-13d947456543` |
| `mean_reversion` | SOL-USDT-SWAP | 1H | -1338.94 | -13.39% | 60.5% | 24.29% | 0.82 | -1.23 | 43 | `987dbd8e-0b05-40d4-a7d7-b09ec6751e5d` |
| `multi_ema` | BTC-USDT-SWAP | 15m | -8292.23 | -82.92% | 21.1% | 86.07% | 0.26 | -5.11 | 190 | `77cc3743-d6dc-410b-8424-278d39b899f8` |
| `multi_ema` | BTC-USDT-SWAP | 1H | -2672.61 | -26.73% | 27.1% | 39.58% | 0.63 | -2.62 | 48 | `affe96ab-0c6e-42ad-b507-2bd5e7af8b69` |
| `multi_ema` | ETH-USDT-SWAP | 15m | -9679.26 | -96.79% | 18.2% | 98.36% | 0.10 | -5.54 | 198 | `cc10b1e9-6b36-4b3d-9216-5fe97509facc` |
| `multi_ema` | ETH-USDT-SWAP | 1H | -8678.97 | -86.79% | 11.3% | 88.15% | 0.05 | -10.42 | 53 | `6722d47e-bc01-49b1-befc-db8e47e4ec71` |
| `multi_ema` | SOL-USDT-SWAP | 15m | -1990.48 | -19.90% | 26.6% | 22.76% | 0.72 | -2.04 | 64 | `2e6022d4-bbd4-42bb-9123-e9289e47cc25` |
| `multi_ema` | SOL-USDT-SWAP | 1H | -6014.78 | -60.15% | 15.9% | 63.85% | 0.26 | -8.15 | 44 | `138737d3-30ee-4046-8de4-4546f6d34225` |
| `multi_factor` | BTC-USDT-SWAP | 15m | 728.53 | 7.29% | 42.9% | 22.55% | 1.08 | 0.43 | 161 | `6302cb82-fc8e-4bd3-8d1a-87f10e9b58e3` |
| `multi_factor` | BTC-USDT-SWAP | 1H | 782.13 | 7.82% | 40.5% | 16.78% | 1.18 | 0.87 | 42 | `2c3aa57c-be42-4758-bfe6-a6143c836da5` |
| `multi_factor` | ETH-USDT-SWAP | 15m | -5705.18 | -57.05% | 41.3% | 61.20% | 0.54 | -3.16 | 138 | `ad81f590-5c83-4efd-b404-30a45f148fb8` |
| `multi_factor` | ETH-USDT-SWAP | 1H | -3026.64 | -30.27% | 37.8% | 38.71% | 0.55 | -3.46 | 37 | `ec856039-7fa9-4973-a3ba-107b1d17eedf` |
| `multi_factor` | SOL-USDT-SWAP | 15m | -801.67 | -8.02% | 39.1% | 13.86% | 0.78 | -1.40 | 69 | `d9b154b1-d8ce-44d6-aaeb-3820386c9638` |
| `multi_factor` | SOL-USDT-SWAP | 1H | -459.59 | -4.60% | 38.5% | 20.07% | 0.92 | -0.48 | 39 | `092eeed4-e0d0-46f6-b072-9580befc9090` |
| `rsi_bollinger_combo` | BTC-USDT-SWAP | 15m | 8509.71 | 85.10% | 68.9% | 14.20% | 1.76 | 2.95 | 164 | `e5ec3935-d8d6-48b5-8927-0fdffb58df20` |
| `rsi_bollinger_combo` | BTC-USDT-SWAP | 1H | -2946.05 | -29.46% | 56.8% | 42.76% | 0.62 | -2.98 | 37 | `b7fc57af-5902-4692-88ec-2ee6f2a98ded` |
| `rsi_bollinger_combo` | ETH-USDT-SWAP | 15m | 16130.84 | 161.31% | 68.0% | 40.48% | 1.39 | 1.75 | 153 | `9831bb4d-5a07-4df0-b986-ab851969dc4f` |
| `rsi_bollinger_combo` | ETH-USDT-SWAP | 1H | 58151.93 | 581.52% | 65.1% | 12.02% | 2.72 | 4.41 | 43 | `1bd221b0-98a5-43d0-ad7f-e09fd590b15c` |
| `rsi_bollinger_combo` | SOL-USDT-SWAP | 15m | -1573.92 | -15.74% | 55.2% | 24.38% | 0.57 | -2.77 | 58 | `a84501f6-91c3-45a9-95ab-9366dbf2da0d` |
| `rsi_bollinger_combo` | SOL-USDT-SWAP | 1H | 1698.53 | 16.99% | 65.9% | 13.21% | 1.24 | 1.39 | 44 | `8a4b8728-ae44-479a-a4a1-5df703c733dd` |
| `rsi_bollinger_regime` | BTC-USDT-SWAP | 15m | 3002.79 | 30.03% | 60.8% | 12.98% | 1.65 | 2.88 | 97 | `547fff98-11d2-4361-9733-4e8b3a4d6834` |
| `rsi_bollinger_regime` | BTC-USDT-SWAP | 1H | -1319.29 | -13.19% | 39.1% | 16.95% | 0.42 | -4.90 | 23 | `44803c68-819e-4ba8-b74a-695f56efb91f` |
| `rsi_bollinger_regime` | ETH-USDT-SWAP | 15m | 8333.05 | 83.33% | 58.8% | 25.24% | 1.51 | 1.94 | 97 | `22ef11c7-4c85-40e9-bfc4-b3432222b044` |
| `rsi_bollinger_regime` | ETH-USDT-SWAP | 1H | 31513.24 | 315.13% | 54.2% | 21.06% | 3.07 | 4.59 | 24 | `98c5cdda-3806-454d-8c30-47ed89606d07` |
| `rsi_bollinger_regime` | SOL-USDT-SWAP | 15m | -793.63 | -7.94% | 30.3% | 13.22% | 0.55 | -3.28 | 33 | `06c5d813-c365-41be-bd6f-76c6a47949bb` |
| `rsi_bollinger_regime` | SOL-USDT-SWAP | 1H | -814.05 | -8.14% | 50.0% | 14.30% | 0.73 | -1.87 | 24 | `ae415124-ee05-4a1c-bdda-32daa5ea60b0` |
| `volume_momentum` | BTC-USDT-SWAP | 15m | -5366.06 | -53.66% | 17.8% | 55.17% | 0.12 | -11.34 | 45 | `12ef4f44-a4d0-4de8-9908-5043be980079` |
| `volume_momentum` | BTC-USDT-SWAP | 1H | -2352.87 | -23.53% | 42.4% | 32.49% | 0.45 | -4.26 | 33 | `75492609-2031-4b72-bfe5-964f0283bf32` |
| `volume_momentum` | ETH-USDT-SWAP | 15m | -9723.34 | -97.23% | 15.9% | 98.35% | 0.04 | -9.45 | 113 | `ba0bc2d4-d56c-42b1-bdb5-482cf76b19a0` |
| `volume_momentum` | ETH-USDT-SWAP | 1H | -8828.24 | -88.28% | 14.0% | 89.32% | 0.02 | -14.47 | 57 | `6c74c13d-2396-4c61-8300-5408884011c4` |
| `volume_momentum` | SOL-USDT-SWAP | 15m | -379.71 | -3.80% | 31.6% | 9.27% | 0.75 | -1.69 | 19 | `eeb3a833-9e63-4b54-af64-f6fe904297dc` |
| `volume_momentum` | SOL-USDT-SWAP | 1H | -5387.33 | -53.87% | 20.8% | 55.39% | 0.17 | -9.13 | 48 | `d65f0df3-5bf1-4122-a1de-fdddaeb996ac` |

## 에러

에러 없음.

## 다음 단계

1. 종합 순위 상위 3개만 2024~2026 장기 구간으로 재검증한다.
2. 장기 구간을 학습/검증/미래검증으로 나눠 워크포워드 검증한다.
3. 후보별 파라미터 스윕은 상위 후보에만 제한한다. 모든 전략을 무작정 최적화하면 과최적화 위험이 크다.
4. 실거래는 아직 금지. 데모도 후보 전략의 신호 관찰용으로만 사용한다.

> 이 리포트는 전략 연구용 백테스트 비교이며, 투자 조언이나 수익 보장이 아닙니다.
