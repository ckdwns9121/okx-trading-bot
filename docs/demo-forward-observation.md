# Demo Forward Observation Plan

작성일: 2026-05-01

## 목적

`rsi_bollinger_regime`의 `risk_profile=limited`를 실거래 전에 OKX demo에서 최소 4주 관찰한다. 이 단계는 수익 확정이 아니라 주문 실패, 슬리피지, 드로다운, 연속 손실 정지를 확인하는 안전 검증이다.

## 부트스트랩

API가 실행 중이고 `.env`가 `OKX_MODE=demo`인지 먼저 확인한다.

```bash
docker compose up -d --build
cd bot
python scripts/bootstrap_demo_observation.py
```

기본 실행은 dry-run이며 BTC/ETH/SOL `1H`, 레버리지 2, `rsi_bollinger_regime` limited 프로필 설정만 출력한다.

설정을 API에 저장만 하려면:

```bash
cd bot
python scripts/bootstrap_demo_observation.py --apply
```

데모 엔진까지 시작하려면:

```bash
cd bot
python scripts/bootstrap_demo_observation.py --apply --start
```

스크립트는 다음 조건이 아니면 중단한다.

- 로컬 설정과 실행 중 API 모두 `OKX_MODE=demo`
- DB health가 `ok`
- `RISK_FAIL_CLOSED=true`
- 전체 DD 한도 `MAX_TOTAL_DRAWDOWN_PCT <= 10`
- 첫 관찰 단계의 `MAX_POSITION_SIZE_PCT <= 10`

## 관찰 지표

매일 기록한다.

- 총/일간/월간 실현 PnL
- 최대 드로다운
- 거래 수, 승률, 평균 손익비
- 연속 손실 수와 pause 발생 여부
- 주문 실패, stale position, reconciliation 오류
- 백테스트 대비 슬리피지 악화 여부

## 통과/탈락 기준

통과 후보가 되려면 4주 동안 전체 DD 10% 미만, 반복 주문 장애 없음, pause가 과도하게 반복되지 않아야 한다. 한도 도달, 리스크 체크 오류, 또는 슬리피지 악화가 확인되면 즉시 중단하고 live 검토는 보류한다.
