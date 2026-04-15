"""Tests for app.core.yaml_config."""

import textwrap
from pathlib import Path
from unittest.mock import patch

from app.core.yaml_config import (
    AppConfig,
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
        cfg = AppConfig()
        w = cfg.valuation.weights
        total = (
            w.base_rate
            + w.rule_analysis
            + w.microstructure
            + w.cross_market
            + w.event_signal
            + w.pattern_kg
            + w.temporal
            + w.crowd_calibration
            + w.cross_platform
        )
        assert abs(total - 1.0) < 1e-9

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
