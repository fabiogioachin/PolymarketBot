"""Tests for AlertManager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.monitoring.alerting import (
    Alert,
    AlertManager,
    AlertRuleConfig,
    AlertType,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def manager() -> AlertManager:
    """AlertManager without a Telegram client."""
    return AlertManager()


@pytest.fixture()
def manager_with_telegram() -> tuple[AlertManager, MagicMock]:
    """AlertManager wired to a mock TelegramClient."""
    telegram = MagicMock()
    telegram.is_configured = True
    telegram.send_alert = AsyncMock(return_value=True)
    mgr = AlertManager(telegram_client=telegram)
    return mgr, telegram


# ── should_alert ──────────────────────────────────────────────────────────────


class TestShouldAlert:
    def test_returns_true_for_enabled_rule(self, manager: AlertManager) -> None:
        assert manager.should_alert(AlertType.CIRCUIT_BREAKER) is True

    def test_returns_false_for_disabled_rule(self, manager: AlertManager) -> None:
        manager.configure_rule(
            AlertRuleConfig(alert_type=AlertType.ANOMALY, enabled=False)
        )
        assert manager.should_alert(AlertType.ANOMALY) is False

    def test_returns_false_for_unknown_type(self, manager: AlertManager) -> None:
        assert manager.should_alert(AlertType.NEW_PATTERN) is False

    def test_min_edge_passes_when_edge_meets_threshold(
        self, manager: AlertManager
    ) -> None:
        # TRADE_EXECUTED rule has min_edge=0.10
        assert manager.should_alert(AlertType.TRADE_EXECUTED, edge=0.10) is True
        assert manager.should_alert(AlertType.TRADE_EXECUTED, edge=0.15) is True

    def test_min_edge_blocks_when_edge_below_threshold(
        self, manager: AlertManager
    ) -> None:
        assert manager.should_alert(AlertType.TRADE_EXECUTED, edge=0.05) is False

    def test_cooldown_blocks_repeated_alerts(self, manager: AlertManager) -> None:
        # Manually set a recent last-sent time
        manager._last_sent[AlertType.ANOMALY] = datetime.now(tz=UTC)
        # Add the ANOMALY rule with a 300 s cooldown
        manager.configure_rule(AlertRuleConfig(alert_type=AlertType.ANOMALY, enabled=True))
        assert manager.should_alert(AlertType.ANOMALY) is False

    def test_cooldown_passes_after_expiry(self, manager: AlertManager) -> None:
        # Set last-sent to far in the past
        manager._last_sent[AlertType.DAILY_LOSS] = datetime.now(tz=UTC) - timedelta(
            seconds=400
        )
        assert manager.should_alert(AlertType.DAILY_LOSS) is True

    def test_circuit_breaker_ignores_cooldown(self, manager: AlertManager) -> None:
        # Set last-sent to now — cooldown_seconds=0 should still pass
        manager._last_sent[AlertType.CIRCUIT_BREAKER] = datetime.now(tz=UTC)
        assert manager.should_alert(AlertType.CIRCUIT_BREAKER) is True


# ── send_alert ────────────────────────────────────────────────────────────────


class TestSendAlert:
    async def test_records_in_history(self, manager: AlertManager) -> None:
        alert = Alert(alert_type=AlertType.ANOMALY, title="test", body="body")
        await manager.send_alert(alert)
        assert alert in manager.get_alert_history()

    async def test_updates_last_sent_timestamp(self, manager: AlertManager) -> None:
        alert = Alert(alert_type=AlertType.ANOMALY, title="t", body="b")
        before = datetime.now(tz=UTC)
        await manager.send_alert(alert)
        after = datetime.now(tz=UTC)
        ts = manager._last_sent[AlertType.ANOMALY]
        assert before <= ts <= after

    async def test_delegates_to_telegram_when_configured(
        self, manager_with_telegram: tuple[AlertManager, MagicMock]
    ) -> None:
        mgr, telegram = manager_with_telegram
        alert = Alert(alert_type=AlertType.ANOMALY, title="T", body="B")
        result = await mgr.send_alert(alert)
        assert result is True
        telegram.send_alert.assert_called_once_with("T", "B")

    async def test_returns_true_without_telegram(self, manager: AlertManager) -> None:
        alert = Alert(alert_type=AlertType.ANOMALY, title="t", body="b")
        result = await manager.send_alert(alert)
        assert result is True
        assert alert.sent is True


# ── check_and_alert_trade ─────────────────────────────────────────────────────


class TestCheckAndAlertTrade:
    async def test_sends_when_edge_above_threshold(self, manager: AlertManager) -> None:
        result = await manager.check_and_alert_trade(
            market_id="mkt-1",
            strategy="momentum",
            side="BUY",
            size=10.0,
            edge=0.12,
        )
        assert result is True

    async def test_skips_when_edge_below_threshold(self, manager: AlertManager) -> None:
        result = await manager.check_and_alert_trade(
            market_id="mkt-2",
            strategy="arb",
            side="SELL",
            size=5.0,
            edge=0.05,
        )
        assert result is False

    async def test_alert_body_contains_trade_details(
        self, manager: AlertManager
    ) -> None:
        await manager.check_and_alert_trade(
            market_id="mkt-xyz",
            strategy="value",
            side="BUY",
            size=8.0,
            edge=0.20,
        )
        history = manager.get_alert_history()
        assert history
        body = history[-1].body
        assert "mkt-xyz" in body
        assert "value" in body
        assert "8.00" in body


# ── check_and_alert_circuit_breaker ───────────────────────────────────────────


class TestCheckAndAlertCircuitBreaker:
    async def test_always_sends(self, manager: AlertManager) -> None:
        # Call twice — cooldown=0 means both succeed
        r1 = await manager.check_and_alert_circuit_breaker("3 consecutive losses")
        r2 = await manager.check_and_alert_circuit_breaker("15% drawdown")
        assert r1 is True
        assert r2 is True

    async def test_body_contains_reason(self, manager: AlertManager) -> None:
        reason = "daily drawdown exceeded"
        await manager.check_and_alert_circuit_breaker(reason)
        history = manager.get_alert_history()
        assert history[-1].body == reason


# ── check_and_alert_daily_loss ────────────────────────────────────────────────


class TestCheckAndAlertDailyLoss:
    async def test_triggers_at_80_percent_of_limit(self, manager: AlertManager) -> None:
        # limit=20, 80% = -16; -16 <= -16 → should trigger
        result = await manager.check_and_alert_daily_loss(daily_pnl=-16.0, limit=20.0)
        assert result is True

    async def test_triggers_beyond_80_percent(self, manager: AlertManager) -> None:
        result = await manager.check_and_alert_daily_loss(daily_pnl=-18.0, limit=20.0)
        assert result is True

    async def test_does_not_trigger_below_threshold(
        self, manager: AlertManager
    ) -> None:
        # -10 > -16 → should NOT trigger
        result = await manager.check_and_alert_daily_loss(daily_pnl=-10.0, limit=20.0)
        assert result is False

    async def test_does_not_trigger_for_positive_pnl(
        self, manager: AlertManager
    ) -> None:
        result = await manager.check_and_alert_daily_loss(daily_pnl=5.0, limit=20.0)
        assert result is False


# ── configure_rule / get_rules ────────────────────────────────────────────────


class TestConfigureRule:
    def test_updates_existing_rule(self, manager: AlertManager) -> None:
        manager.configure_rule(
            AlertRuleConfig(
                alert_type=AlertType.TRADE_EXECUTED,
                enabled=True,
                min_edge=0.20,
            )
        )
        rule = manager._rules[AlertType.TRADE_EXECUTED]
        assert rule.min_edge == 0.20

    def test_adds_new_rule(self, manager: AlertManager) -> None:
        manager.configure_rule(
            AlertRuleConfig(alert_type=AlertType.NEW_PATTERN, enabled=True)
        )
        assert AlertType.NEW_PATTERN in manager._rules

    def test_get_rules_returns_all_configured(self, manager: AlertManager) -> None:
        rules = manager.get_rules()
        types = {r.alert_type for r in rules}
        # Verify the default rules are present
        assert AlertType.TRADE_EXECUTED in types
        assert AlertType.CIRCUIT_BREAKER in types
        assert AlertType.DAILY_SUMMARY in types


# ── get_alert_history ─────────────────────────────────────────────────────────


class TestGetAlertHistory:
    async def test_returns_recent_alerts(self, manager: AlertManager) -> None:
        for i in range(5):
            await manager.send_alert(
                Alert(alert_type=AlertType.ANOMALY, title=f"alert-{i}", body="")
            )
        history = manager.get_alert_history(limit=3)
        assert len(history) == 3
        assert history[-1].title == "alert-4"

    async def test_default_limit_is_50(self, manager: AlertManager) -> None:
        for i in range(60):
            await manager.send_alert(
                Alert(alert_type=AlertType.ANOMALY, title=f"a{i}", body="")
            )
        history = manager.get_alert_history()
        assert len(history) == 50
