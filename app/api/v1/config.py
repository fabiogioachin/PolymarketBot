"""Configuration CRUD API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.yaml_config import app_config

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# --- Request/Response models ---


class TriggerRule(BaseModel):
    type: str
    enabled: bool = True
    min_edge: float | None = None


class TriggerConfig(BaseModel):
    llm_enabled: bool = False
    triggers: list[str] = Field(default_factory=list)
    max_daily_calls: int = 20
    model: str = "claude-sonnet-4-6"


class AlertConfig(BaseModel):
    telegram_enabled: bool = False
    rules: list[TriggerRule] = Field(default_factory=list)


class FullConfig(BaseModel):
    llm: TriggerConfig
    alerts: AlertConfig


# --- In-memory overrides (persisted until restart) ---
# These override yaml_config values at runtime

_llm_overrides: dict[str, object] = {}
_alert_overrides: dict[str, object] = {}

_VALID_TRIGGERS = {"anomaly", "new_market", "daily_digest", "manual_request"}


@router.get("/triggers")
async def get_triggers() -> TriggerConfig:
    """Get current LLM trigger configuration."""
    return TriggerConfig(
        llm_enabled=_llm_overrides.get("enabled", app_config.llm.enabled),  # type: ignore[arg-type]
        triggers=_llm_overrides.get("triggers", app_config.llm.triggers),  # type: ignore[arg-type]
        max_daily_calls=_llm_overrides.get(  # type: ignore[arg-type]
            "max_daily_calls", app_config.llm.max_daily_calls
        ),
        model=_llm_overrides.get("model", app_config.llm.model),  # type: ignore[arg-type]
    )


@router.put("/triggers")
async def update_triggers(config: TriggerConfig) -> TriggerConfig:
    """Update LLM trigger configuration (in-memory override)."""
    for t in config.triggers:
        if t not in _VALID_TRIGGERS:
            raise HTTPException(status_code=400, detail=f"Invalid trigger: {t}")

    _llm_overrides["enabled"] = config.llm_enabled
    _llm_overrides["triggers"] = config.triggers
    _llm_overrides["max_daily_calls"] = config.max_daily_calls
    _llm_overrides["model"] = config.model

    logger.info("llm_config_updated", llm_enabled=config.llm_enabled, triggers=config.triggers)
    return config


@router.get("/alerts")
async def get_alerts() -> AlertConfig:
    """Get current alert configuration."""
    default_rules = [
        TriggerRule(type=rule.type, enabled=True, min_edge=rule.min_edge)
        for rule in app_config.telegram.alert_rules
    ]
    return AlertConfig(
        telegram_enabled=_alert_overrides.get(  # type: ignore[arg-type]
            "enabled", app_config.telegram.enabled
        ),
        rules=_alert_overrides.get("rules", default_rules),  # type: ignore[arg-type]
    )


@router.put("/alerts")
async def update_alerts(config: AlertConfig) -> AlertConfig:
    """Update alert configuration (in-memory override)."""
    _alert_overrides["enabled"] = config.telegram_enabled
    _alert_overrides["rules"] = config.rules

    logger.info(
        "alert_config_updated",
        telegram_enabled=config.telegram_enabled,
        rules_count=len(config.rules),
    )
    return config


@router.get("")
async def get_full_config() -> FullConfig:
    """Get full configuration."""
    triggers = await get_triggers()
    alerts = await get_alerts()
    return FullConfig(llm=triggers, alerts=alerts)


@router.post("/reset")
async def reset_config() -> dict[str, str]:
    """Reset all in-memory overrides to YAML defaults."""
    _llm_overrides.clear()
    _alert_overrides.clear()
    logger.info("config_reset")
    return {"status": "reset", "message": "Config reset to YAML defaults"}
