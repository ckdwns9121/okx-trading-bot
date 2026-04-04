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
    MAX_POSITION_SIZE_PCT: float = 10.0

    TELEGRAM_NOTIFICATIONS_ENABLED: bool = True
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    TELEGRAM_COMMANDS_ENABLED: bool = True
    TELEGRAM_POLL_TIMEOUT_SEC: int = 25

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
