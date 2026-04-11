# Chronos Regime Hybrid Strategy

Strategy name: `chronos_regime_hybrid`

## What it does

- Uses Chronos-2 median forecast (`q50`) as directional edge.
- Uses prediction spread (`q90 - q10`) as uncertainty guard.
- Uses market regime detection to block counter-trend entries.
- Falls back to `rsi_bollinger_regime` when Chronos inference is unavailable.

## Enable

### 0) Install ML dependencies

Chronos dependencies are optional and not installed in the base image.

- Local Python:

```bash
cd bot
pip install ".[ml]"
```

- Docker build:

```bash
docker compose build --build-arg INSTALL_ML_EXTRAS=true bot
docker compose up -d bot
```

1. Set `.env`:

```env
CHRONOS_ENABLED=true
CHRONOS_MODEL_ID=amazon/chronos-2
CHRONOS_DEVICE_MAP=cpu
CHRONOS_TIMEOUT_SEC=12
```

2. Restart bot container (no rebuild needed for env-only changes):

```bash
docker compose up -d bot
```

3. In configuration, choose strategy `chronos_regime_hybrid` for your pair.

## Optional tuning (environment defaults)

- `CHRONOS_PREDICTION_LENGTH` (default: 8)
- `CHRONOS_MIN_CONTEXT` (default: 256)
- `CHRONOS_TIMEOUT_SEC` (default: 12)
- `CHRONOS_ENTRY_EDGE_PCT` (default: 0.25)
- `CHRONOS_EXIT_EDGE_PCT` (default: 0.08)
- `CHRONOS_MAX_UNCERTAINTY_PCT` (default: 1.2)
