"""Application settings loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class PolymarketSettings(BaseSettings):
    api_key: str = ""
    secret: str = ""
    passphrase: str = ""
    funder: str = ""

    model_config = {"env_prefix": "POLYMARKET_"}


class TelegramSettings(BaseSettings):
    bot_token: str = ""
    chat_id: str = ""

    model_config = {"env_prefix": "TELEGRAM_"}


class ObsidianSettings(BaseSettings):
    api_key: str = ""
    api_url: str = "http://127.0.0.1:27123"

    model_config = {"env_prefix": "OBSIDIAN_"}


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    dry_run: bool = True
    anthropic_api_key: str = ""

    polymarket: PolymarketSettings = Field(default_factory=PolymarketSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    obsidian: ObsidianSettings = Field(default_factory=ObsidianSettings)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
