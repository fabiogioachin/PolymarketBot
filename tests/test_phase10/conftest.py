"""Shared fixtures for Phase 10 tests."""

import pytest

import app.core.yaml_config as yaml_cfg_module
from app.core.yaml_config import AppConfig, StrategiesConfig


@pytest.fixture(autouse=True)
def _patch_yaml_config_phase10(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure strategy registry finds test strategies as enabled."""
    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=["priority_test", "high_edge"],
            domain_filters={},
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)
