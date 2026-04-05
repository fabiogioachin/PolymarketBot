## Active
Lessons that affect future tasks. Target: under 15 entries.

### 2026-04-04 — [codebase] Python 3.11 not 3.12
**Context**: `pip install -e ".[dev]"` during Session 1.1 scaffold
**What happened**: pyproject.toml had `requires-python = ">=3.12"` but system has Python 3.11.9. Also `target-version = "py312"` in ruff config.
**Root cause**: todo.md spec assumed Python 3.12+, but dev machine only has 3.11.
**Action**: Always check `python --version` before setting requires-python. Current project uses `>=3.11` and `target-version = "py311"`.

### 2026-04-04 — [tool] hatchling editable install broken on this pip
**Context**: `pip install -e ".[dev]"` failed with `AttributeError: module 'hatchling.build' has no attribute 'prepare_metadata_for_build_editable'`
**What happened**: Even after upgrading pip+hatchling, editable install still failed. Workaround: install deps directly with `pip install`.
**Root cause**: pip/hatchling version incompatibility on Windows Python 3.11 from Microsoft Store.
**Action**: For this project, use `pip install <deps>` directly instead of `pip install -e ".[dev]"`. Consider switching to uv or a venv with standard Python installer in future.

### 2026-04-05 — [codebase] Signal must carry market_price, not just edge
**Context**: Full project review — execution engine used `signal.edge_amount` as order price
**What happened**: Orders placed at ~0.05 (the edge) instead of ~0.65 (the market price). Position sizing, risk checks, everything downstream was wrong.
**Root cause**: Signal model lacked market_price field. Engine had no other way to get the price for the token being traded.
**Action**: Every Signal must set `market_price` from the valuation. Engine uses `signal.market_price` for orders, not edge. All strategies updated.

### 2026-04-05 — [codebase] DI must be wired before endpoints are useful
**Context**: Bot API and dashboard returned hardcoded placeholders
**What happened**: dependencies.py only had MarketService and RiskKB. No DI for ExecutionEngine, BotService, RiskManager, CircuitBreaker, StrategyRegistry, ValueAssessmentEngine.
**Root cause**: Phase 6 left DI wiring as "Phase 6 TODO" but it was never done.
**Action**: dependencies.py now provides the full service graph. New modules must register their singletons here. Dashboard and bot API read live state.

### 2026-04-05 — [codebase] Strategies returning list[Signal] for multi-leg trades
**Context**: Arbitrage needed two-legged execution (BUY YES + BUY NO)
**What happened**: BaseStrategy protocol returned `Signal | None`, forcing one-legged arb (= directional bet).
**Root cause**: Protocol designed for single-signal strategies; arbitrage is inherently multi-leg.
**Action**: BaseStrategy.evaluate now returns `Signal | list[Signal] | None`. Engine normalizes to list. Any future multi-leg strategy follows same pattern.

### 2026-04-05 — [codebase] External plan assumptions must be verified against actual code
**Context**: /feature with user-provided MANIFOLD_INTEGRATION_PLAN.md
**What happened**: The plan assumed `SignalType` enum contained signal sources (it contains BUY/SELL/HOLD), that the VAE used a `signals` dict (it uses individual float params), and that `config.yaml` existed (only `config.example.yaml` does). Planning-specialist caught all 3 and produced a corrected plan.
**Root cause**: Plan was written from memory/documentation, not from reading the actual code.
**Action**: Always run codebase exploration before planning, even when user provides a detailed plan. Verify every file path, class name, and method signature referenced in external plans.

### 2026-04-05 — [codebase] assess_batch needs external_signals forwarding pattern
**Context**: Wiring Manifold cross-platform signal into the VAE
**What happened**: `assess_batch()` had no way to pass per-market external signals to individual `assess()` calls. Added a generic `external_signals: dict[str, dict[str, float | None]]` parameter.
**Root cause**: Original design only supported signals computed internally by the engine (base_rate, microstructure, etc.), not externally-provided per-market signals.
**Action**: The `external_signals` pattern is now the standard way to inject per-market signals from satellite sources. Use it for any future data integrations.

## Archive
Resolved or one-off entries. Not read by agents.
