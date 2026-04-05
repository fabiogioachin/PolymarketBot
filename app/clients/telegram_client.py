"""Telegram bot client for alerts and commands."""

from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class TelegramClient:
    """Sends messages via Telegram Bot API and handles commands."""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, bot_token: str = "", chat_id: str = "") -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._base_url = self.BASE_URL.format(token=bot_token) if bot_token else ""

    @property
    def is_configured(self) -> bool:
        """Return True when both token and chat_id are set."""
        return bool(self._token and self._chat_id)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.is_configured:
            logger.warning("telegram_not_configured")
            return False

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10.0,
            )
            if response.status_code == 200:
                return True
            logger.error("telegram_send_failed", status=response.status_code)
            return False

    async def send_alert(self, title: str, body: str) -> bool:
        """Send a formatted alert."""
        message = f"🚨 <b>{title}</b>\n\n{body}"
        return await self.send_message(message)

    async def send_trade_notification(
        self,
        market_id: str,
        strategy: str,
        side: str,
        size: float,
        edge: float,
    ) -> bool:
        """Send trade execution notification."""
        emoji = "📈" if side == "BUY" else "📉"
        message = (
            f"{emoji} <b>Trade Executed</b>\n\n"
            f"Market: <code>{market_id}</code>\n"
            f"Strategy: {strategy}\n"
            f"Side: {side}\n"
            f"Size: {size:.2f} EUR\n"
            f"Edge: {edge:.4f}"
        )
        return await self.send_message(message)

    async def send_daily_summary(
        self,
        total_trades: int,
        pnl: float,
        win_rate: float,
        equity: float,
    ) -> bool:
        """Send daily performance summary."""
        emoji = "✅" if pnl >= 0 else "❌"
        message = (
            f"📊 <b>Daily Summary</b>\n\n"
            f"Trades: {total_trades}\n"
            f"P&L: {emoji} {pnl:+.2f} EUR\n"
            f"Win Rate: {win_rate:.1f}%\n"
            f"Equity: {equity:.2f} EUR"
        )
        return await self.send_message(message)

    async def send_circuit_breaker_alert(self, reason: str) -> bool:
        """Send circuit breaker trip alert."""
        message = (
            f"⛔ <b>Circuit Breaker Tripped!</b>\n\n"
            f"Reason: {reason}\n"
            f"Trading halted until cooldown expires."
        )
        return await self.send_message(message)


class TelegramCommandHandler:
    """Handles incoming Telegram bot commands."""

    COMMANDS: dict[str, str] = {
        "/status": "Get bot status",
        "/positions": "Show open positions",
        "/pnl": "Show P&L summary",
        "/watchlist": "Show GDELT watchlist",
        "/help": "Show available commands",
    }

    def handle_status(
        self,
        bot_running: bool,
        mode: str,
        tick_count: int,
        pnl: float,
    ) -> str:
        """Format /status response."""
        status = "🟢 Running" if bot_running else "🔴 Stopped"
        return (
            f"<b>Bot Status</b>\n\n"
            f"Status: {status}\n"
            f"Mode: {mode}\n"
            f"Ticks: {tick_count}\n"
            f"Daily P&L: {pnl:+.2f} EUR"
        )

    def handle_positions(self, positions: list[dict[str, object]]) -> str:
        """Format /positions response."""
        if not positions:
            return "No open positions."
        lines = ["<b>Open Positions</b>\n"]
        for p in positions:
            lines.append(
                f"• {p.get('market_id', '?')} | {p.get('side', '?')} | "
                f"{float(p.get('size', 0)):.2f} @ {float(p.get('price', 0)):.4f}"
            )
        return "\n".join(lines)

    def handle_pnl(self, daily_pnl: float, total_pnl: float, win_rate: float) -> str:
        """Format /pnl response."""
        return (
            f"<b>P&L Summary</b>\n\n"
            f"Daily: {daily_pnl:+.2f} EUR\n"
            f"Total: {total_pnl:+.2f} EUR\n"
            f"Win Rate: {win_rate:.1f}%"
        )

    def handle_help(self) -> str:
        """Format /help response."""
        lines = ["<b>Available Commands</b>\n"]
        for cmd, desc in self.COMMANDS.items():
            lines.append(f"{cmd} — {desc}")
        return "\n".join(lines)
