"""Tests for StrategyRegistry."""

import pytest

from app.strategies.registry import StrategyRegistry


class DummyStrategy:
    """Minimal concrete strategy satisfying the BaseStrategy Protocol."""

    def __init__(self, name: str = "test_strategy", domains: list[str] | None = None):
        self._name = name
        self._domains = domains or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def domain_filter(self) -> list[str]:
        return self._domains

    async def evaluate(self, market, valuation, knowledge=None):
        return None


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> StrategyRegistry:
    return StrategyRegistry()


@pytest.fixture
def strategy_a() -> DummyStrategy:
    return DummyStrategy(name="strategy_a", domains=[])


@pytest.fixture
def strategy_b() -> DummyStrategy:
    return DummyStrategy(name="strategy_b", domains=["politics", "economics"])


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_register_appears_in_get_all(registry: StrategyRegistry, strategy_a: DummyStrategy) -> None:
    registry.register(strategy_a)
    assert strategy_a in registry.get_all()


def test_get_returns_correct_strategy(
    registry: StrategyRegistry, strategy_a: DummyStrategy
) -> None:
    registry.register(strategy_a)
    result = registry.get("strategy_a")
    assert result is strategy_a


def test_get_returns_none_for_unknown(registry: StrategyRegistry) -> None:
    assert registry.get("nonexistent") is None


def test_get_all_multiple_strategies(
    registry: StrategyRegistry,
    strategy_a: DummyStrategy,
    strategy_b: DummyStrategy,
) -> None:
    registry.register(strategy_a)
    registry.register(strategy_b)
    all_strategies = registry.get_all()
    assert len(all_strategies) == 2
    assert strategy_a in all_strategies
    assert strategy_b in all_strategies


def test_unregister_removes_strategy(
    registry: StrategyRegistry, strategy_a: DummyStrategy
) -> None:
    registry.register(strategy_a)
    registry.unregister("strategy_a")
    assert registry.get("strategy_a") is None
    assert strategy_a not in registry.get_all()


def test_unregister_nonexistent_is_safe(registry: StrategyRegistry) -> None:
    # Should not raise
    registry.unregister("does_not_exist")


def test_get_enabled_respects_yaml_config(
    registry: StrategyRegistry,
    strategy_a: DummyStrategy,
    strategy_b: DummyStrategy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.strategies.registry as reg_module
    from app.core.yaml_config import AppConfig, StrategiesConfig

    cfg = AppConfig(strategies=StrategiesConfig(enabled=["strategy_a"], domain_filters={}))
    monkeypatch.setattr(reg_module, "app_config", cfg, raising=False)

    # Patch at import time inside the function scope
    import app.core.yaml_config as yaml_cfg_module
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)

    registry.register(strategy_a)
    registry.register(strategy_b)

    enabled = registry.get_enabled()
    assert strategy_a in enabled
    assert strategy_b not in enabled


def test_get_for_domain_empty_filter_matches_all(
    registry: StrategyRegistry,
    strategy_a: DummyStrategy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strategy with empty domain_filter applies to any domain."""
    import app.core.yaml_config as yaml_cfg_module
    from app.core.yaml_config import AppConfig, StrategiesConfig

    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=["strategy_a"],
            domain_filters={"strategy_a": []},
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)

    registry.register(strategy_a)

    assert strategy_a in registry.get_for_domain("politics")
    assert strategy_a in registry.get_for_domain("sports")
    assert strategy_a in registry.get_for_domain("crypto")


def test_get_for_domain_specific_filter_restricts(
    registry: StrategyRegistry,
    strategy_b: DummyStrategy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strategy with specific domain_filter only matches those domains."""
    import app.core.yaml_config as yaml_cfg_module
    from app.core.yaml_config import AppConfig, StrategiesConfig

    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=["strategy_b"],
            domain_filters={"strategy_b": ["politics", "economics"]},
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)

    registry.register(strategy_b)

    assert strategy_b in registry.get_for_domain("politics")
    assert strategy_b in registry.get_for_domain("economics")
    assert strategy_b not in registry.get_for_domain("sports")
    assert strategy_b not in registry.get_for_domain("crypto")


def test_get_for_domain_excludes_disabled(
    registry: StrategyRegistry,
    strategy_a: DummyStrategy,
    strategy_b: DummyStrategy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_for_domain only returns strategies that are both enabled and domain-matching."""
    import app.core.yaml_config as yaml_cfg_module
    from app.core.yaml_config import AppConfig, StrategiesConfig

    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=["strategy_b"],  # strategy_a is NOT enabled
            domain_filters={
                "strategy_a": [],
                "strategy_b": ["politics"],
            },
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)

    registry.register(strategy_a)
    registry.register(strategy_b)

    result = registry.get_for_domain("politics")
    assert strategy_b in result
    assert strategy_a not in result
