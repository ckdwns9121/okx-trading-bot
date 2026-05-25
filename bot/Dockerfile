FROM python:3.12-slim

WORKDIR /app

ARG INSTALL_ML_EXTRAS=false

COPY pyproject.toml ./
COPY app/ ./app/
COPY scripts/ ./scripts/

RUN if [ "$INSTALL_ML_EXTRAS" = "true" ]; then \
      pip install --no-cache-dir ".[ml]"; \
    else \
      pip install --no-cache-dir .; \
    fi

COPY alembic/ ./alembic/
COPY alembic.ini ./

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
