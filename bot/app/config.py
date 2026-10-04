from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OKX_API_KEY: str
    OKX_SECRET: str
    OKX_PASSPHRASE: str

    OKX_MODE: Literal["demo", "live"] = "demo"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/trading"

    MAX_DAILY_LOSS_USD: float = 100.0
    RISK_MAX_ORDER_NOTIONAL_USD: float = 1000.0
    RISK_MAX_INSTRUMENT_NOTIONAL_USD: float = 2000.0
    RISK_MAX_TOTAL_EXPOSURE_USD: float = 4000.0
    RISK_MAX_PRICE_DEVIATION_PCT: float = 1.0
    RISK_MAX_ORDERS_PER_MINUTE: int = 6
    RISK_KILL_SWITCH_FILE: str = "state/kill_switch.json"
    RISK_EXECUTION_LOG_FILE: str = "state/execution_quality.jsonl"
    PAPER_TREND_STATE_FILE: str = "state/trend_following_paper.json"
    DEMO_TREND_STATE_FILE: str = "state/trend_following_demo.json"
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

    MICROSTRUCTURE_GATE_ENABLED: bool = False
    MICROSTRUCTURE_ORDER_BOOK_DEPTH: int = 5
    MICROSTRUCTURE_MAX_SPREAD_PCT: float = 0.5
    MICROSTRUCTURE_MIN_VISIBLE_DEPTH_NOTIONAL: float = 0.0
    MICROSTRUCTURE_MAX_MARKET_DATA_AGE_SECONDS: float = 5.0

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
