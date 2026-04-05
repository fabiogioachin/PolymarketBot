"""Alert manager: rule-based alerting system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class AlertType(StrEnum):
    TRADE_EXECUTED = "trade_executed"
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_SUMMARY = "daily_summary"
    ANOMALY = "anomaly"
    EDGE_FOUND = "edge_found"
    DAILY_LOSS = "daily_loss"
    NEW_PATTERN = "new_pattern"


@dataclass
class Alert:
    """A triggered alert."""

    alert_type: AlertType
    title: str = ""
    body: str = ""
    timestamp: datetime | None = None
    sent: bool = False


@dataclass
class AlertRuleConfig:
    """Configuration for an alert rule."""

    alert_type: AlertType
    enabled: bool = True
    min_edge: float | None = None  # only trigger if edge >= min_edge
    cooldown_seconds: int = 300  # minimum time between same alert type


# Silence false-positive "field default" warnings from dataclasses when used
# as a type annotation — the field() call is intentional.
_SENTINEL: list[AlertRuleConfig] = field(default_factory=list)  # type: ignore[assignment]


class AlertManager:
    """Manages alert rules and dispatches alerts."""

    def __init__(self, telegram_client: object = None) -> None:
        self._telegram = telegram_client
        self._rules: dict[AlertType, AlertRuleConfig] = {}
        self._last_sent: dict[AlertType, datetime] = {}
        self._alert_history: list[Alert] = []

        # Default rules
        self._rules[AlertType.TRADE_EXECUTED] = AlertRuleConfig(
            alert_type=AlertType.TRADE_EXECUTED, min_edge=0.10
        )
        self._rules[AlertType.CIRCUIT_BREAKER] = AlertRuleConfig(
            alert_type=AlertType.CIRCUIT_BREAKER,
            cooldown_seconds=0,  # always alert
        )
        self._rules[AlertType.DAILY_SUMMARY] = AlertRuleConfig(
            alert_type=AlertType.DAILY_SUMMARY
        )
        self._rules[AlertType.DAILY_LOSS] = AlertRuleConfig(
            alert_type=AlertType.DAILY_LOSS
        )
        self._rules[AlertType.ANOMALY] = AlertRuleConfig(
            alert_type=AlertType.ANOMALY
        )
        self._rules[AlertType.EDGE_FOUND] = AlertRuleConfig(
            alert_type=AlertType.EDGE_FOUND, min_edge=0.15
        )

    def configure_rule(self, rule: AlertRuleConfig) -> None:
        """Add or update an alert rule."""
        self._rules[rule.alert_type] = rule

    def should_alert(self, alert_type: AlertType, edge: float | None = None) -> bool:
        """Check if an alert should be sent based on rules and cooldown."""
        rule = self._rules.get(alert_type)
        if not rule or not rule.enabled:
            return False

        # Check min edge
        if rule.min_edge is not None and edge is not None and edge < rule.min_edge:
            return False

        # Check cooldown
        last = self._last_sent.get(alert_type)
        if last and rule.cooldown_seconds > 0:
            elapsed = (datetime.now(tz=UTC) - last).total_seconds()
            if elapsed < rule.cooldown_seconds:
                return False

        return True

    async def send_alert(self, alert: Alert) -> bool:
        """Send an alert via configured channels."""
        self._alert_history.append(alert)
        self._last_sent[alert.alert_type] = datetime.now(tz=UTC)

        if self._telegram is not None and getattr(self._telegram, "is_configured", False):
            result: bool = await self._telegram.send_alert(alert.title, alert.body)
            alert.sent = result
            return result

        logger.info("alert_generated", type=alert.alert_type, title=alert.title)
        alert.sent = True
        return True

    async def check_and_alert_trade(
        self,
        market_id: str,
        strategy: str,
        side: str,
        size: float,
        edge: float,
    ) -> bool:
        """Check rules and send trade alert if applicable."""
        if not self.should_alert(AlertType.TRADE_EXECUTED, edge=edge):
            return False

        alert = Alert(
            alert_type=AlertType.TRADE_EXECUTED,
            title="Trade Executed",
            body=(
                f"Market: {market_id}\n"
                f"Strategy: {strategy}\n"
                f"Side: {side}\n"
                f"Size: {size:.2f} EUR\n"
                f"Edge: {edge:.4f}"
            ),
            timestamp=datetime.now(tz=UTC),
        )
        return await self.send_alert(alert)

    async def check_and_alert_circuit_breaker(self, reason: str) -> bool:
        """Send circuit breaker alert (always fires — cooldown=0)."""
        if not self.should_alert(AlertType.CIRCUIT_BREAKER):
            return False

        alert = Alert(
            alert_type=AlertType.CIRCUIT_BREAKER,
            title="Circuit Breaker Tripped",
            body=reason,
            timestamp=datetime.now(tz=UTC),
        )
        return await self.send_alert(alert)

    async def check_and_alert_daily_loss(self, daily_pnl: float, limit: float) -> bool:
        """Alert when daily loss reaches or exceeds 80 % of the limit."""
        if not self.should_alert(AlertType.DAILY_LOSS):
            return False

        # Only alert when 80 %+ of limit consumed (daily_pnl is negative)
        if daily_pnl > -limit * 0.8:
            return False

        alert = Alert(
            alert_type=AlertType.DAILY_LOSS,
            title="Daily Loss Warning",
            body=f"Daily P&L: {daily_pnl:.2f} EUR\nLimit: {limit:.2f} EUR",
            timestamp=datetime.now(tz=UTC),
        )
        return await self.send_alert(alert)

    def get_alert_history(self, limit: int = 50) -> list[Alert]:
        """Return the most recent alerts (up to *limit*)."""
        return self._alert_history[-limit:]

    def get_rules(self) -> list[AlertRuleConfig]:
        """Return all configured alert rules."""
        return list(self._rules.values())
