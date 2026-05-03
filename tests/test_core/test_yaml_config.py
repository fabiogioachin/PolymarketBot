"""Tests for app.core.yaml_config."""

import textwrap
from pathlib import Path
from unittest.mock import patch

from app.core.yaml_config import (
    AppConfig,
    BotConfig,
    WeightsConfig,
    _load_config,
    app_config,
    reload_config,
)


class TestAppConfigDefaults:
    def test_app_meta(self) -> None:
        cfg = AppConfig()
        assert cfg.app.name == "polymarket-bot"
        assert cfg.app.version == "0.1.0"

    def test_polymarket(self) -> None:
        cfg = AppConfig()
        assert cfg.polymarket.rate_limit == 10
        assert cfg.polymarket.retry_max == 3
        assert cfg.polymarket.retry_backoff == 1.0

    def test_execution(self) -> None:
        cfg = AppConfig()
        assert cfg.execution.mode == "dry_run"
        assert cfg.execution.tick_interval_seconds == 60
        assert cfg.execution.shadow_mode is False

    def test_risk_with_circuit_breaker(self) -> None:
        cfg = AppConfig()
        assert cfg.risk.max_exposure_pct == 50.0
        assert cfg.risk.circuit_breaker.consecutive_losses == 3
        assert cfg.risk.circuit_breaker.cooldown_minutes == 60

    def test_valuation_weights_sum(self) -> None:
        """Weights sum must stay inside the permissive [0.95, 1.15] range.

        Phase 13 S4b adds whale_pressure + insider_pressure (nominal sum 1.10)
        so this test enumerates all numeric weight fields dynamically to stay
        robust against future additions.
        """
        cfg = AppConfig()
        w = cfg.valuation.weights
        total = sum(
            v for v in w.model_dump().values() if isinstance(v, int | float)
        )
        assert 0.95 <= total <= 1.15, f"sum={total}"

    def test_valuation_weights_include_whale_and_insider(self) -> None:
        w = WeightsConfig()
        assert hasattr(w, "whale_pressure")
        assert hasattr(w, "insider_pressure")
        assert w.whale_pressure == 0.05
        assert w.insider_pressure == 0.05

    def test_valuation_weights_validator_rejects_out_of_range(self) -> None:
        """Validator must reject an obviously unbalanced configuration."""
        import pytest
        from pydantic import ValidationError

        # Crush every weight to 0 except one → sum ≈ 0.15 → below 0.95 → reject.
        with pytest.raises(ValidationError):
            WeightsConfig(
                base_rate=0.15,
                rule_analysis=0.0,
                microstructure=0.0,
                cross_market=0.0,
                event_signal=0.0,
                pattern_kg=0.0,
                temporal=0.0,
                crowd_calibration=0.0,
                cross_platform=0.0,
                whale_pressure=0.0,
                insider_pressure=0.0,
            )

    def test_strategies_defaults(self) -> None:
        cfg = AppConfig()
        assert "value_edge" in cfg.strategies.enabled
        assert cfg.strategies.domain_filters["event_driven"] == [
            "politics",
            "geopolitics",
            "economics",
        ]

    def test_llm_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.llm.enabled is False
        assert cfg.llm.max_daily_calls == 20
        assert cfg.llm.model == "claude-sonnet-4-6"

    def test_gdelt_defaults(self) -> None:
        cfg = AppConfig()
        gdelt = cfg.intelligence.gdelt
        assert gdelt.poll_interval_minutes == 60
        assert gdelt.watchlist["themes"] == [
            "ELECTION",
            "ECON_INFLATION",
            "WB_CONFLICT",
        ]
        assert len(gdelt.watchlist["themes"]) == 3


class TestLoadConfig:
    def test_loads_from_example_yaml(self) -> None:
        """The example config should parse without errors."""
        cfg = _load_config()
        assert cfg.app.name == "polymarket-bot"

    def test_reload_returns_config(self) -> None:
        cfg = reload_config()
        assert isinstance(cfg, AppConfig)


class TestAppConfigSingleton:
    def test_module_level_singleton(self) -> None:
        assert isinstance(app_config, AppConfig)
        assert app_config.app.name == "polymarket-bot"


class TestPartialYamlOverride:
    def test_partial_override(self, tmp_path: Path) -> None:
        """Only override a subset of fields; rest should use defaults."""
        yaml_content = textwrap.dedent("""\
            app:
              name: custom-bot
            risk:
              max_positions: 5
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        with patch("app.core.yaml_config._CONFIG_PATH", config_file):
            cfg = _load_config()

        assert cfg.app.name == "custom-bot"
        assert cfg.app.version == "0.1.0"  # default preserved
        assert cfg.risk.max_positions == 5
        assert cfg.risk.max_exposure_pct == 50.0  # default preserved


class TestBotConfig:
    """Phase 13 fix-1: bot.auto_start drives lifespan startup behavior."""

    def test_default_auto_start_true(self) -> None:
        cfg = AppConfig()
        assert cfg.bot.auto_start is True
        assert cfg.bot.tick_interval_seconds == 60

    def test_bot_config_types(self) -> None:
        b = BotConfig()
        assert isinstance(b.auto_start, bool)
        assert isinstance(b.tick_interval_seconds, int)

    def test_bot_auto_start_override_false(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            bot:
              auto_start: false
              tick_interval_seconds: 30
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        with patch("app.core.yaml_config._CONFIG_PATH", config_file):
            cfg = _load_config()

        assert cfg.bot.auto_start is False
        assert cfg.bot.tick_interval_seconds == 30

    def test_bot_section_in_example_yaml(self) -> None:
        """Example YAML must declare bot.auto_start so it loads to True."""
        cfg = _load_config()
        assert cfg.bot.auto_start is True


class TestIntelligenceSchedulerConfig:
    """Phase 13 S4b — Team B: ``intelligence.scheduler.*`` YAML block.

    The IntelligenceScheduler runs four independent asyncio loops (whale,
    popular, leaderboard, snapshot). Their intervals must be configurable via
    YAML under ``intelligence.scheduler``.
    """

    def test_yaml_config_loads_scheduler_block(self, tmp_path: Path) -> None:
        """``intelligence.scheduler.whale_interval_seconds`` is read from YAML."""
        yaml_content = textwrap.dedent("""\
            intelligence:
              scheduler:
                enabled: true
                whale_interval_seconds: 45
                popular_interval_seconds: 200
                leaderboard_interval_seconds: 800
                snapshot_interval_seconds: 250
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        with patch("app.core.yaml_config._CONFIG_PATH", config_file):
            cfg = _load_config()

        sched = cfg.intelligence.scheduler
        assert sched.enabled is True
        assert sched.whale_interval_seconds == 45
        assert sched.popular_interval_seconds == 200
        assert sched.leaderboard_interval_seconds == 800
        assert sched.snapshot_interval_seconds == 250
