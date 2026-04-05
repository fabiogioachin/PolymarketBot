"""Tests for app.core.config."""

from app.core.config import ObsidianSettings, PolymarketSettings, Settings, TelegramSettings


class TestPolymarketSettings:
    def test_defaults(self) -> None:
        s = PolymarketSettings()
        assert s.api_key == ""
        assert s.secret == ""
        assert s.passphrase == ""
        assert s.funder == ""


class TestTelegramSettings:
    def test_defaults(self) -> None:
        s = TelegramSettings()
        assert s.bot_token == ""
        assert s.chat_id == ""


class TestObsidianSettings:
    def test_defaults(self) -> None:
        s = ObsidianSettings()
        assert s.api_key == ""
        assert s.api_url == "http://127.0.0.1:27123"


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.app_env == "development"
        assert s.log_level == "INFO"
        assert s.dry_run is True
        assert s.anthropic_api_key == ""

    def test_nested_settings(self) -> None:
        s = Settings()
        assert isinstance(s.polymarket, PolymarketSettings)
        assert isinstance(s.telegram, TelegramSettings)
        assert isinstance(s.obsidian, ObsidianSettings)
