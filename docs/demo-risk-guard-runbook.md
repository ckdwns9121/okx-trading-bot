# Demo Risk Guard Runbook

작성일: 2026-04-27

## 목적

`rsi_bollinger_regime`을 실거래가 아니라 OKX demo/paper에서 관찰하기 위한 안전 실행 절차다. 이 설정은 백테스트에서 DD가 낮아진 `risk_profile="limited"`를 demo 실행 경로에 자동 적용하고, 손실 제한 규칙으로 신규 진입을 막는다.

## 적용되는 보호 장치

Demo 모드에서 활성 전략이 `rsi_bollinger_regime`이면 LiveEngine이 다음 기본값을 주입한다.

```json
{
  "risk_profile": "limited",
  "tail_risk_overlay_enabled": true,
  "risk_hard_stop_pct": 2.0,
  "risk_trailing_activation_pct": 1.5,
  "risk_trailing_stop_pct": 0.8,
  "time_stop_candles": 12,
  "time_stop_edge_pct": 0.05,
  "degrade_after_losses": 2,
  "pause_after_losses": 3,
  "pause_minutes": 1440
}
```

추가 전역 제한:

- `MAX_DAILY_LOSS_USD`: 하루 실현손실 한도
- `MAX_MONTHLY_LOSS_USD`: 월간 실현손실 한도
- `RISK_STARTING_EQUITY_USD` + `MAX_TOTAL_DRAWDOWN_PCT`: 전체 누적 손실 한도
- `RISK_FAIL_CLOSED=true`: 리스크 확인 실패 시 신규 진입 차단
- 기존 포지션이 있으면 같은 pair 신규 진입 차단

## 권장 demo 설정

처음 4주는 1H만 사용한다.

```bash
OKX_MODE=demo
RISK_STARTING_EQUITY_USD=10000
MAX_TOTAL_DRAWDOWN_PCT=10
MAX_DAILY_LOSS_USD=200
MAX_MONTHLY_LOSS_USD=1000
RISK_FAIL_CLOSED=true
```

전략 config 예시:

```json
{
  "strategy_name": "rsi_bollinger_regime",
  "pair": "BTC-USDT-SWAP",
  "timeframe": "1H",
  "parameters_json": {},
  "leverage": 2,
  "is_active": true
}
```

`parameters_json`이 비어 있어도 demo 모드에서는 `risk_profile="limited"`가 자동 적용된다. ETH/SOL도 같은 방식으로 추가하되, SOL 15m는 아직 사용하지 않는다.

## 중지 기준

다음 중 하나라도 발생하면 demo 관찰을 중단한다.

- 일일 손실 한도 도달
- 전체 DD 10% 도달
- 연속 손실 3회로 24시간 pause 발생이 반복됨
- 주문 실패 또는 stale position 이벤트가 반복됨
- 백테스트보다 슬리피지가 명확히 악화됨

## 다음 단계

4주간 demo 로그와 체결 데이터를 모은 뒤 `docs/`에 관찰 리포트를 작성한다. 통과 전에는 live 모드로 전환하지 않는다.

## 검증 증거

- 단위 테스트: `tests/test_demo_risk_guard.py` → 10개 통과.
- 전체 백엔드 테스트: `cd bot && OKX_API_KEY=dummy OKX_SECRET=dummy OKX_PASSPHRASE=dummy /tmp/okx-bot-venv/bin/python -m pytest -q` → 39개 통과.
- 독립 검증: Ralph verifier가 daily/monthly/total drawdown 차단, demo-only `risk_profile=limited`, 중복 포지션 차단, 문서/env 반영을 승인.
