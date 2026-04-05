"""Base strategy protocol."""

from typing import Protocol, runtime_checkable

from app.models.knowledge import KnowledgeContext
from app.models.market import Market
from app.models.signal import Signal
from app.models.valuation import ValuationResult


@runtime_checkable
class BaseStrategy(Protocol):
    """Protocol that all trading strategies must satisfy."""

    @property
    def name(self) -> str:
        """Unique strategy identifier."""
        ...

    @property
    def domain_filter(self) -> list[str]:
        """Market domains this strategy applies to. Empty = all domains."""
        ...

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | list[Signal] | None:
        """Evaluate a market and return signal(s), or None if no signal.

        Strategies may return a single Signal, a list of Signals (e.g. for
        multi-leg trades like arbitrage), or None.
        """
        ...
