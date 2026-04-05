"""Tests for TelegramClient and TelegramCommandHandler."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.telegram_client import TelegramClient, TelegramCommandHandler

BOT_TOKEN = "123456:ABC-DEF"
CHAT_ID = "987654321"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def unconfigured_client() -> TelegramClient:
    return TelegramClient()


@pytest.fixture()
def configured_client() -> TelegramClient:
    return TelegramClient(bot_token=BOT_TOKEN, chat_id=CHAT_ID)


@pytest.fixture()
def handler() -> TelegramCommandHandler:
    return TelegramCommandHandler()


# ── TelegramClient: is_configured ─────────────────────────────────────────────


class TestIsConfigured:
    def test_false_without_credentials(self, unconfigured_client: TelegramClient) -> None:
        assert unconfigured_client.is_configured is False

    def test_false_with_token_only(self) -> None:
        client = TelegramClient(bot_token=BOT_TOKEN)
        assert client.is_configured is False

    def test_false_with_chat_id_only(self) -> None:
        client = TelegramClient(chat_id=CHAT_ID)
        assert client.is_configured is False

    def test_true_with_both(self, configured_client: TelegramClient) -> None:
        assert configured_client.is_configured is True


# ── TelegramClient: send_message ──────────────────────────────────────────────


class TestSendMessage:
    async def test_returns_false_when_not_configured(
        self, unconfigured_client: TelegramClient
    ) -> None:
        result = await unconfigured_client.send_message("hello")
        assert result is False

    @respx.mock
    async def test_returns_true_on_200(self, configured_client: TelegramClient) -> None:
        respx.post(BASE_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        result = await configured_client.send_message("hello")
        assert result is True

    @respx.mock
    async def test_returns_false_on_error_status(
        self, configured_client: TelegramClient
    ) -> None:
        respx.post(BASE_URL).mock(return_value=httpx.Response(400, json={"ok": False}))
        result = await configured_client.send_message("hello")
        assert result is False

    @respx.mock
    async def test_calls_telegram_api(self, configured_client: TelegramClient) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await configured_client.send_message("test text")
        assert route.called


# ── TelegramClient: send_trade_notification ───────────────────────────────────


class TestSendTradeNotification:
    @respx.mock
    async def test_buy_formats_correctly(self, configured_client: TelegramClient) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await configured_client.send_trade_notification(
            market_id="market-123",
            strategy="momentum",
            side="BUY",
            size=10.0,
            edge=0.12,
        )
        assert result is True
        body = route.calls.last.request.content.decode()
        assert "market-123" in body
        assert "BUY" in body
        assert "momentum" in body
        assert "10.00" in body
        assert "0.1200" in body
        assert "📈" in body

    @respx.mock
    async def test_sell_uses_down_arrow(self, configured_client: TelegramClient) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await configured_client.send_trade_notification(
            market_id="market-456",
            strategy="arb",
            side="SELL",
            size=5.0,
            edge=0.08,
        )
        body = route.calls.last.request.content.decode()
        assert "📉" in body


# ── TelegramClient: send_daily_summary ────────────────────────────────────────


class TestSendDailySummary:
    @respx.mock
    async def test_positive_pnl_uses_checkmark(
        self, configured_client: TelegramClient
    ) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await configured_client.send_daily_summary(
            total_trades=5, pnl=3.50, win_rate=60.0, equity=103.50
        )
        assert result is True
        body = route.calls.last.request.content.decode()
        assert "5" in body
        assert "60.0" in body
        assert "103.50" in body
        assert "✅" in body

    @respx.mock
    async def test_negative_pnl_uses_cross(self, configured_client: TelegramClient) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await configured_client.send_daily_summary(
            total_trades=3, pnl=-5.0, win_rate=33.3, equity=95.0
        )
        body = route.calls.last.request.content.decode()
        assert "❌" in body


# ── TelegramClient: send_circuit_breaker_alert ────────────────────────────────


class TestSendCircuitBreakerAlert:
    @respx.mock
    async def test_formats_reason_correctly(
        self, configured_client: TelegramClient
    ) -> None:
        route = respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await configured_client.send_circuit_breaker_alert(
            reason="3 consecutive losses"
        )
        assert result is True
        body = route.calls.last.request.content.decode()
        assert "3 consecutive losses" in body
        assert "⛔" in body
        assert "halted" in body


# ── TelegramCommandHandler ────────────────────────────────────────────────────


class TestHandleStatus:
    def test_running_bot(self, handler: TelegramCommandHandler) -> None:
        output = handler.handle_status(
            bot_running=True, mode="dry_run", tick_count=42, pnl=1.23
        )
        assert "🟢 Running" in output
        assert "dry_run" in output
        assert "42" in output
        assert "+1.23" in output

    def test_stopped_bot(self, handler: TelegramCommandHandler) -> None:
        output = handler.handle_status(
            bot_running=False, mode="live", tick_count=0, pnl=-2.00
        )
        assert "🔴 Stopped" in output
        assert "-2.00" in output


class TestHandlePositions:
    def test_empty_positions(self, handler: TelegramCommandHandler) -> None:
        assert handler.handle_positions([]) == "No open positions."

    def test_with_positions(self, handler: TelegramCommandHandler) -> None:
        positions = [
            {"market_id": "mkt-1", "side": "BUY", "size": 10.0, "price": 0.6543},
        ]
        output = handler.handle_positions(positions)
        assert "mkt-1" in output
        assert "BUY" in output
        assert "10.00" in output
        assert "0.6543" in output


class TestHandleHelp:
    def test_lists_all_commands(self, handler: TelegramCommandHandler) -> None:
        output = handler.handle_help()
        for cmd in handler.COMMANDS:
            assert cmd in output

    def test_includes_descriptions(self, handler: TelegramCommandHandler) -> None:
        output = handler.handle_help()
        for desc in handler.COMMANDS.values():
            assert desc in output


class TestHandlePnl:
    def test_formats_pnl(self, handler: TelegramCommandHandler) -> None:
        output = handler.handle_pnl(daily_pnl=1.5, total_pnl=-3.0, win_rate=55.5)
        assert "+1.50" in output
        assert "-3.00" in output
        assert "55.5" in output
