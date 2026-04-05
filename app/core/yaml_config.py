"""YAML configuration loader with Pydantic validation."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"
_EXAMPLE_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.example.yaml"


# ── Nested config models ──────────────────────────────────────────────


class AppMeta(BaseModel):
    name: str = "polymarket-bot"
    version: str = "0.1.0"
    env: str = "development"
    log_level: str = "INFO"
    dry_run: bool = True


class PolymarketConfig(BaseModel):
    base_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    rate_limit: int = 10
    retry_max: int = 3
    retry_backoff: float = 1.0


class ExecutionConfig(BaseModel):
    mode: str = "dry_run"
    tick_interval_seconds: int = 60
    shadow_mode: bool = False


class CircuitBreakerConfig(BaseModel):
    consecutive_losses: int = 3
    daily_drawdown_pct: float = 15.0
    cooldown_minutes: int = 60


class RiskConfig(BaseModel):
    """Risk configuration.

    max_single_position_eur and daily_loss_limit_eur accept either:
    - A fixed EUR value (e.g., 25.0)
    - A percentage string of equity (e.g., "5%")
    The RiskManager resolves percentages at runtime against current equity.
    """

    max_exposure_pct: float = 50.0
    max_single_position_eur: float | str = 25.0
    daily_loss_limit_eur: float | str = 20.0
    fixed_fraction_pct: float = 5.0
    max_positions: int = 25
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


class WeightsConfig(BaseModel):
    base_rate: float = 0.15
    rule_analysis: float = 0.15
    microstructure: float = 0.20
    cross_market: float = 0.10
    event_signal: float = 0.15
    pattern_kg: float = 0.10
    temporal: float = 0.10
    crowd_calibration: float = 0.05


class ThresholdsConfig(BaseModel):
    min_edge: float = 0.05
    min_confidence: float = 0.3
    strong_edge: float = 0.15


class ValuationConfig(BaseModel):
    tick_interval_seconds: int = 120
    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)


class GdeltConfig(BaseModel):
    enabled: bool = True
    poll_interval_minutes: int = 15
    watchlist: dict[str, list[str]] = Field(default_factory=lambda: {
        "themes": [
            "ELECTION",
            "ECON_INFLATION",
            "ECON_INTEREST_RATE",
            "CLIMATE_CHANGE",
            "WB_CONFLICT",
        ],
        "actors": ["USA", "RUS", "CHN", "EU"],
        "countries": ["US", "RU", "CN", "UA", "IL"],
    })


class RssFeed(BaseModel):
    name: str
    url: str


class RssConfig(BaseModel):
    enabled: bool = True
    poll_interval_minutes: int = 30
    feeds: list[RssFeed] = Field(default_factory=lambda: [
        RssFeed(name="Reuters World", url="https://feeds.reuters.com/Reuters/worldNews"),
        RssFeed(name="AP Top News", url="https://rsshub.app/apnews/topics/apf-topnews"),
        RssFeed(name="BBC World", url="https://feeds.bbci.co.uk/news/world/rss.xml"),
        RssFeed(name="Al Jazeera", url="https://www.aljazeera.com/xml/rss/all.xml"),
    ])


class ObsidianKgConfig(BaseModel):
    vault_path: str = (
        "C:/Users/fgioa/OneDrive - SYNESIS CONSORTIUM/Desktop/PRO/_ObsidianKnowledge"
    )
    patterns_path: str = "Projects/PolymarketBot/patterns"
    enabled: bool = True


class IntelligenceConfig(BaseModel):
    gdelt: GdeltConfig = Field(default_factory=GdeltConfig)
    rss: RssConfig = Field(default_factory=RssConfig)
    obsidian: ObsidianKgConfig = Field(default_factory=ObsidianKgConfig)


class AlertRule(BaseModel):
    type: str
    min_edge: float | None = None


class StrategiesConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: [
        "value_edge",
        "arbitrage",
        "rule_edge",
        "event_driven",
        "resolution",
    ])
    domain_filters: dict[str, list[str]] = Field(default_factory=lambda: {
        "value_edge": [],
        "arbitrage": [],
        "rule_edge": [],
        "event_driven": ["politics", "geopolitics", "economics"],
        "resolution": ["sports", "crypto"],
    })


class TelegramAlertConfig(BaseModel):
    enabled: bool = False
    alert_rules: list[AlertRule] = Field(default_factory=lambda: [
        AlertRule(type="trade_executed", min_edge=0.10),
        AlertRule(type="circuit_breaker"),
        AlertRule(type="daily_summary"),
    ])


class LlmConfig(BaseModel):
    enabled: bool = False
    triggers: list[str] = Field(default_factory=lambda: [
        "anomaly",
        "new_market",
        "daily_digest",
    ])
    max_daily_calls: int = 20
    model: str = "claude-sonnet-4-6"


# ── Top-level config ──────────────────────────────────────────────────


class AppConfig(BaseModel):
    app: AppMeta = Field(default_factory=AppMeta)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    intelligence: IntelligenceConfig = Field(default_factory=IntelligenceConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    telegram: TelegramAlertConfig = Field(default_factory=TelegramAlertConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)


# ── Loader ────────────────────────────────────────────────────────────


def _load_config() -> AppConfig:
    """Load and validate config from YAML, falling back to example."""
    config_file = _CONFIG_PATH if _CONFIG_PATH.exists() else _EXAMPLE_CONFIG_PATH

    if config_file.exists():
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        return AppConfig.model_validate(raw)

    # No config file at all — use pure defaults
    return AppConfig()


def reload_config() -> AppConfig:
    """Re-read and re-validate configuration from disk."""
    global app_config  # noqa: PLW0603
    app_config = _load_config()
    return app_config


app_config: AppConfig = _load_config()
