"""Tests for app.main lifespan: bot auto-start behavior.

Phase 13 fix-1: when ``app_config.bot.auto_start`` is True (default), the
FastAPI lifespan must call ``BotService.start(interval_seconds=...)`` after
``setup_logging``. When False, the bot must NOT start and a structured log
``bot_auto_start_skipped`` is emitted.

We patch ``app.main.get_bot_service`` with a stub so we exercise the lifespan
branching without spinning up the real ExecutionEngine, WS listener, and all
intelligence orchestrators. The lifespan async-context-manager is invoked
directly (httpx ASGITransport does not propagate ASGI lifespan events, so
relying on it would silently skip the code under test).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.main as main_module


class _StubBotService:
    """Minimal BotService stand-in for lifespan testing.

    Mirrors the public surface used by ``app.main.lifespan``:
    ``start(interval_seconds: int)`` and ``stop()``. Exposes ``running`` so
    tests can assert lifecycle transitions.
    """

    def __init__(self) -> None:
        self.running: bool = False
        self.last_interval: int | None = None
        self.start_calls: int = 0
        self.stop_calls: int = 0

    async def start(self, interval_seconds: int = 60) -> None:
        self.running = True
        self.last_interval = interval_seconds
        self.start_calls += 1

    async def stop(self) -> None:
        self.running = False
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_lifespan_auto_starts_bot_when_enabled() -> None:
    """Default config: auto_start=True → bot.start invoked, bot.running True."""
    stub = _StubBotService()

    async def _get_stub() -> _StubBotService:
        return stub

    fake_app = FastAPI()
    with (
        patch.object(main_module, "get_bot_service", _get_stub),
        patch.object(main_module.app_config.bot, "auto_start", True),
        patch.object(main_module.app_config.bot, "tick_interval_seconds", 42),
    ):
        async with main_module.lifespan(fake_app):
            assert stub.running is True
            assert stub.start_calls == 1
            assert stub.last_interval == 42

    # After context exit, lifespan shutdown should have called stop().
    assert stub.stop_calls == 1
    assert stub.running is False


@pytest.mark.asyncio
async def test_lifespan_skips_bot_when_disabled() -> None:
    """auto_start=False → get_bot_service NOT called, no start, no stop."""
    stub = _StubBotService()
    call_count = {"n": 0}

    async def _get_stub() -> _StubBotService:
        call_count["n"] += 1
        return stub

    fake_app = FastAPI()
    with (
        patch.object(main_module, "get_bot_service", _get_stub),
        patch.object(main_module.app_config.bot, "auto_start", False),
    ):
        async with main_module.lifespan(fake_app):
            assert stub.running is False
            assert stub.start_calls == 0

    # When auto_start is False, lifespan must not even resolve the bot service
    # (avoids spinning up the dependency graph just to skip it).
    assert call_count["n"] == 0
    assert stub.stop_calls == 0


@pytest.mark.asyncio
async def test_lifespan_uses_configured_tick_interval() -> None:
    """The interval passed to start() must come from bot.tick_interval_seconds."""
    stub = _StubBotService()

    async def _get_stub() -> _StubBotService:
        return stub

    fake_app = FastAPI()
    with (
        patch.object(main_module, "get_bot_service", _get_stub),
        patch.object(main_module.app_config.bot, "auto_start", True),
        patch.object(main_module.app_config.bot, "tick_interval_seconds", 17),
    ):
        async with main_module.lifespan(fake_app):
            assert stub.last_interval == 17


@pytest.mark.asyncio
async def test_lifespan_stops_bot_even_if_request_handling_raises() -> None:
    """Cleanup hook must run on exceptions inside the yield window."""
    stub = _StubBotService()

    async def _get_stub() -> _StubBotService:
        return stub

    fake_app = FastAPI()
    with (
        patch.object(main_module, "get_bot_service", _get_stub),
        patch.object(main_module.app_config.bot, "auto_start", True),
        pytest.raises(RuntimeError, match="boom"),
    ):
        async with main_module.lifespan(fake_app):
            assert stub.running is True
            raise RuntimeError("boom")

    assert stub.stop_calls == 1
    assert stub.running is False


@pytest.mark.asyncio
async def test_app_routes_respond_under_asgi_transport() -> None:
    """Sanity: the app still serves HTTP through ASGITransport (no lifespan).

    This is a regression guard — the lifespan auto-start logic must not break
    request handling for tests that use the shared ``client`` fixture.
    """
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/")
        # Root redirects to /static/index.html (307); httpx default doesn't
        # follow redirects, so we just check the status family.
        assert r.status_code in (200, 307)
