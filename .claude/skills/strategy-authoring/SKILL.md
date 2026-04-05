---
name: strategy-authoring
description: >
  Create, modify, and register trading strategies. Use when implementing a new strategy,
  changing evaluate() logic, adjusting domain filters, or debugging signal generation.
  Also trigger when the user asks about strategy behavior or signal flow.
---

# Strategy Authoring

## Protocol (not ABC)

Strategies use `@runtime_checkable Protocol` from `app/strategies/base.py`. Any class satisfying
the shape qualifies — no inheritance needed.

```python
@runtime_checkable
class BaseStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def domain_filter(self) -> list[str]: ...

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | list[Signal] | None: ...
```

## Return Types

- `Signal` — single trade signal (most strategies)
- `list[Signal]` — multi-leg trades (e.g., arbitrage buys YES on one market + NO on another)
- `None` — no action (equivalent to `Signal(signal_type=SignalType.HOLD)`)

## Signal Model (`app/models/signal.py`)

```python
class Signal(BaseModel):
    strategy: str          # name of strategy
    market_id: str
    token_id: str = ""     # which outcome token to trade
    signal_type: SignalType # BUY | SELL | HOLD
    confidence: float = 0.0
    market_price: float = 0.0  # MUST be set — engine uses for orders
    edge_amount: float = 0.0
    suggested_size: float = 0.0
    reasoning: str = ""
    knowledge_sources: list[str] = Field(default_factory=list)
```

**Critical:** `market_price` must always be set. The execution engine uses it for order pricing,
not `edge_amount`.

## Step-by-Step: Add a New Strategy

### 1. Create the strategy file

`app/strategies/my_strategy.py`:

```python
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

class MyStrategy:
    @property
    def name(self) -> str:
        return "my_strategy"

    @property
    def domain_filter(self) -> list[str]:
        return []  # all domains, or ["politics", "crypto"]

    async def evaluate(
        self, market: Market, valuation: ValuationResult, knowledge=None
    ) -> Signal | None:
        # Your logic here
        if some_condition:
            yes_token = next((o for o in market.outcomes if o.outcome.lower() == "yes"), None)
            if not yes_token:
                return None
            return Signal(
                strategy=self.name,
                market_id=market.id,
                token_id=yes_token.token_id,
                signal_type=SignalType.BUY,
                confidence=valuation.confidence,
                market_price=yes_token.price,
                edge_amount=valuation.fee_adjusted_edge,
                reasoning="My reasoning",
            )
        return None
```

### 2. Register in dependencies.py

In `app/core/dependencies.py`, inside `get_strategy_registry()`:

```python
from app.strategies.my_strategy import MyStrategy
# Add to the registration tuple:
MyStrategy(),
```

### 3. Enable in config

In `config/config.example.yaml` (and `config.yaml` if it exists):

```yaml
strategies:
  enabled:
    - my_strategy  # ADD
  domain_filters:
    my_strategy: []  # or specific domains
```

### 4. Write tests

`tests/test_strategies/test_my_strategy.py` — follow `test_value_edge.py` pattern:
- Use `_make_market()` and `_make_valuation()` helper factories
- Test protocol compliance: `assert isinstance(strategy, BaseStrategy)`
- Test boundary conditions (at threshold, above, below)
- Test domain filter behavior
- Test None/HOLD returns

## Current Strategies (7)

| Strategy | Domain Filter | Logic |
|----------|--------------|-------|
| `value_edge` | all | Buys when `fee_adjusted_edge > min_edge` and `confidence > min_confidence` |
| `arbitrage` | all | Multi-leg: buys YES+NO on correlated markets when combined price < 1.0 |
| `rule_edge` | all | Trades on rule clarity signals |
| `event_driven` | politics, geopolitics, economics | Trades on GDELT/news event signals |
| `resolution` | sports, crypto | Trades near resolution when outcome seems clear |
| `sentiment` | all | News sentiment-based signals |
| `knowledge_driven` | all | Obsidian KG pattern-based signals |

## Key Files

| File | Purpose |
|------|---------|
| `app/strategies/base.py` | Protocol definition |
| `app/strategies/registry.py` | StrategyRegistry (dict wrapper) |
| `app/strategies/value_edge.py` | Reference implementation |
| `app/core/dependencies.py` | Registration at startup |
| `config/config.example.yaml` | `strategies.enabled` + `domain_filters` |
