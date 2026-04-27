from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    OKX_API_KEY: str
    OKX_SECRET: str
    OKX_PASSPHRASE: str

    OKX_MODE: Literal["demo", "live"] = "demo"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/trading"

    MAX_DAILY_LOSS_USD: float = 100.0
    MAX_MONTHLY_LOSS_USD: float = 500.0
    RISK_STARTING_EQUITY_USD: float = 10000.0
    MAX_TOTAL_DRAWDOWN_PCT: float = 10.0
    RISK_FAIL_CLOSED: bool = True
    MAX_POSITION_SIZE_PCT: float = 10.0
    MAX_TOTAL_EXPOSURE_PCT: float = 100.0
    MAX_PAIR_EXPOSURE_PCT: float = 100.0

    RISK_VOL_ENABLED: bool = False
    RISK_VOL_LOOKBACK: int = 60
    RISK_VOL_TARGET_PCT: float = 1.5
    RISK_VOL_MIN_SCALE: float = 0.25
    RISK_VOL_MAX_SCALE: float = 1.0

    ORDER_SPLIT_ENABLED: bool = False
    ORDER_SPLIT_PARTS: int = 1
    ORDER_SPLIT_INTERVAL_SEC: float = 0.4
    ORDER_RETRY_MAX_ATTEMPTS: int = 3
    ORDER_RETRY_BACKOFF_SEC: float = 0.6

    TELEGRAM_NOTIFICATIONS_ENABLED: bool = True
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    TELEGRAM_COMMANDS_ENABLED: bool = True
    TELEGRAM_POLL_TIMEOUT_SEC: int = 25

    CHRONOS_ENABLED: bool = False
    CHRONOS_MODEL_ID: str = "amazon/chronos-2"
    CHRONOS_DEVICE_MAP: str = "cpu"
    CHRONOS_TIMEOUT_SEC: float = 12.0
    CHRONOS_PREDICTION_LENGTH: int = 8
    CHRONOS_MIN_CONTEXT: int = 256
    CHRONOS_ENTRY_EDGE_PCT: float = 0.14
    CHRONOS_EXIT_EDGE_PCT: float = 0.03
    CHRONOS_MAX_UNCERTAINTY_PCT: float = 1.4
    CHRONOS_BASE_SIZE_PCT: float = 100.0
    CHRONOS_MIN_SIZE_PCT: float = 35.0
    CHRONOS_REGIME_CONFIDENCE_MIN: float = 0.78

    @property
    def okx_base_url(self) -> str:
        return "https://www.okx.com"

    @property
    def is_demo(self) -> bool:
        return self.OKX_MODE == "demo"

    @property
    def telegram_enabled(self) -> bool:
        return (
            self.TELEGRAM_NOTIFICATIONS_ENABLED
            and bool(self.TELEGRAM_BOT_TOKEN)
            and bool(self.TELEGRAM_CHAT_ID)
        )


settings = Settings()
