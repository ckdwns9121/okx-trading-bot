from __future__ import annotations

import os

# Provide required settings before any app module import so tests never need
# real credentials. The engine is created lazily, so this URL is never dialed.
os.environ.setdefault("OKX_API_KEY", "test-key")
os.environ.setdefault("OKX_SECRET", "test-secret")
os.environ.setdefault("OKX_PASSPHRASE", "test-passphrase")
os.environ.setdefault("OKX_MODE", "demo")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
