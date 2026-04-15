"""Shared fixtures for execution tests."""

import pytest

import app.core.yaml_config as yaml_cfg_module
from app.core.yaml_config import AppConfig, StrategiesConfig


@pytest.fixture(autouse=True)
def _patch_yaml_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure strategy registry finds fake strategies as enabled."""
    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=[
                "fake_strategy",
                "error_strategy",
                "multi_signal_strategy",
                "medium_edge",
            ],
            domain_filters={},
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)
