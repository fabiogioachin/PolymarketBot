"""Tests for the Polymarket WebSocket client listener."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.clients.polymarket_ws import PolymarketWsClient


def _make_client(messages: list[str]) -> PolymarketWsClient:
    """Build a connected client whose ws.recv() yields the given raw messages.

    After the queued messages are exhausted, the listen loop is shut down by
    flipping ``_connected`` to False on the next recv() call.
    """
    client = PolymarketWsClient()
    client._connected = True

    queue = list(messages)

    async def fake_recv() -> str:
        if not queue:
            # Stop the listener cleanly — no reconnect path triggered.
            client._connected = False
            # Returning a sentinel that the loop will discard. The loop checks
            # _connected at the top of the next iteration so this value is
            # never actually processed.
            return json.dumps({"type": "pong"})
        return queue.pop(0)

    ws = AsyncMock()
    ws.recv = AsyncMock(side_effect=fake_recv)
    client._ws = ws
    return client


async def _collect(gen: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async for item in gen:
        out.append(item)
    return out


@pytest.mark.asyncio
async def test_listen_handles_dict_message() -> None:
    """A single dict payload is yielded as-is."""
    client = _make_client([json.dumps({"event_type": "book", "asset_id": "a"})])
    received = await _collect(client.listen())
    assert received == [{"event_type": "book", "asset_id": "a"}]


@pytest.mark.asyncio
async def test_listen_handles_list_message_yields_each_element() -> None:
    """A list payload is split into individual dict events."""
    payload = json.dumps(
        [
            {"event_type": "book", "x": 1},
            {"event_type": "book", "x": 2},
        ]
    )
    client = _make_client([payload])
    received = await _collect(client.listen())
    assert received == [
        {"event_type": "book", "x": 1},
        {"event_type": "book", "x": 2},
    ]


@pytest.mark.asyncio
async def test_listen_skips_pong_in_list() -> None:
    """Pong entries inside a batch are dropped; real events still flow through."""
    payload = json.dumps(
        [
            {"type": "pong"},
            {"event_type": "book", "x": 7},
        ]
    )
    client = _make_client([payload])
    received = await _collect(client.listen())
    assert received == [{"event_type": "book", "x": 7}]


@pytest.mark.asyncio
async def test_listen_skips_top_level_pong_dict() -> None:
    """Single-dict pong payloads are still skipped (regression guard)."""
    client = _make_client(
        [
            json.dumps({"type": "pong"}),
            json.dumps({"event_type": "book", "x": 1}),
        ]
    )
    received = await _collect(client.listen())
    assert received == [{"event_type": "book", "x": 1}]


@pytest.mark.asyncio
async def test_listen_skips_invalid_payload_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-dict elements (string, int, nested list) are logged and skipped.

    Structlog is configured with stdlib at app-startup; in plain unit tests it
    falls back to PrintLogger which writes to stdout. We assert the warning is
    emitted (no crash) regardless of the active sink by inspecting captured
    output for the structured event key.
    """
    payload = json.dumps(["not_a_dict", 123, [1, 2]])
    client = _make_client([payload])

    received = await _collect(client.listen())

    assert received == []
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # One warning per bad element — assert each type appears.
    assert combined.count("ws_unexpected_payload_type") == 3, combined
    assert "type=str" in combined
    assert "type=int" in combined
    assert "type=list" in combined
