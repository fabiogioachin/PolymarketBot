"""Strategy registry — loads and manages strategy instances."""

from app.core.logging import get_logger
from app.strategies.base import BaseStrategy

logger = get_logger(__name__)


class StrategyRegistry:
    """Loads strategies from YAML config, provides domain filtering."""

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy instance."""
        self._strategies[strategy.name] = strategy
        logger.debug("strategy_registered", name=strategy.name)

    def get(self, name: str) -> BaseStrategy | None:
        """Return a strategy by name, or None if not found."""
        return self._strategies.get(name)

    def get_all(self) -> list[BaseStrategy]:
        """Return all registered strategies."""
        return list(self._strategies.values())

    def get_enabled(self) -> list[BaseStrategy]:
        """Return only strategies enabled in YAML config."""
        from app.core.yaml_config import app_config

        enabled_names = app_config.strategies.enabled
        return [s for s in self._strategies.values() if s.name in enabled_names]

    def get_for_domain(self, domain: str) -> list[BaseStrategy]:
        """Return strategies applicable to a market domain."""
        from app.core.yaml_config import app_config

        enabled = self.get_enabled()
        result = []
        for s in enabled:
            domain_filters = app_config.strategies.domain_filters.get(s.name, [])
            # Empty filter = applies to all domains
            if not domain_filters or domain in domain_filters:
                result.append(s)
        return result

    def unregister(self, name: str) -> None:
        """Remove a strategy from the registry."""
        self._strategies.pop(name, None)
        logger.debug("strategy_unregistered", name=name)
