"""WebSocket client for real-time Polymarket orderbook updates."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

from app.core.logging import get_logger
from app.core.yaml_config import app_config

logger = get_logger(__name__)

_HEARTBEAT_INTERVAL = 10  # seconds
_RECONNECT_BASE = 1.0  # initial backoff seconds
_RECONNECT_MAX = 60.0  # max backoff seconds


class PolymarketWsClient:
    """WebSocket client for real-time Polymarket orderbook updates."""

    def __init__(self) -> None:
        self._ws_url = app_config.polymarket.ws_url
        self._ws: Any = None
        self._subscribed_assets: set[str] = set()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._connected = False
        self._reconnect_delay = _RECONNECT_BASE

    async def connect(self) -> None:
        """Connect to WebSocket server."""
        try:
            self._ws = await websockets.connect(self._ws_url)
            self._connected = True
            self._reconnect_delay = _RECONNECT_BASE
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("ws_connected", url=self._ws_url)
        except (OSError, InvalidStatusCode) as exc:
            self._connected = False
            logger.error("ws_connect_failed", url=self._ws_url, error=str(exc))
            raise

    async def subscribe(self, asset_ids: list[str]) -> None:
        """Subscribe to orderbook updates for given assets."""
        if not self._ws or not self._connected:
            raise RuntimeError("WebSocket not connected")

        msg = json.dumps({"type": "subscribe", "assets_ids": asset_ids})
        await self._ws.send(msg)
        self._subscribed_assets.update(asset_ids)
        logger.info("ws_subscribed", asset_ids=asset_ids)

    async def unsubscribe(self, asset_ids: list[str]) -> None:
        """Unsubscribe from assets."""
        if not self._ws or not self._connected:
            raise RuntimeError("WebSocket not connected")

        msg = json.dumps({"type": "unsubscribe", "assets_ids": asset_ids})
        await self._ws.send(msg)
        self._subscribed_assets -= set(asset_ids)
        logger.info("ws_unsubscribed", asset_ids=asset_ids)

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed messages from WebSocket. Handles heartbeat internally.

        Polymarket WS sends both single events (dict) and batches (list of dicts).
        This method normalizes both into a stream of dict events, dropping pong
        replies and logging unexpected payload shapes without crashing the loop.
        """
        while self._connected:
            try:
                if not self._ws:
                    raise RuntimeError("WebSocket not connected")

                raw = await self._ws.recv()
                data = json.loads(raw)

            except ConnectionClosed:
                logger.warning("ws_connection_closed")
                self._connected = False
                await self._attempt_reconnect()
                continue

            except Exception:
                logger.exception("ws_listen_error")
                self._connected = False
                await self._attempt_reconnect()
                continue

            # Normalize single event vs batch into a list of candidates.
            if isinstance(data, list):
                events: list[Any] = data
            else:
                events = [data]

            for event in events:
                if not isinstance(event, dict):
                    logger.warning(
                        "ws_unexpected_payload_type",
                        type=type(event).__name__,
                    )
                    continue

                # Skip pong responses (handled by heartbeat)
                if event.get("type") == "pong":
                    continue

                yield event

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._connected = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                logger.exception("ws_disconnect_error")
            self._ws = None

        self._subscribed_assets.clear()
        logger.info("ws_disconnected")

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected."""
        return self._connected

    async def _heartbeat_loop(self) -> None:
        """Send periodic pings to keep the connection alive."""
        try:
            while self._connected and self._ws:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                if self._connected and self._ws:
                    try:
                        await self._ws.send(json.dumps({"type": "ping"}))
                    except ConnectionClosed:
                        logger.warning("ws_heartbeat_connection_lost")
                        self._connected = False
                        break
        except asyncio.CancelledError:
            pass

    async def _attempt_reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        while not self._connected:
            logger.info("ws_reconnecting", delay=self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)

            try:
                self._ws = await websockets.connect(self._ws_url)
                self._connected = True
                self._reconnect_delay = _RECONNECT_BASE
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                logger.info("ws_reconnected", url=self._ws_url)

                # Re-subscribe to previously subscribed assets
                if self._subscribed_assets:
                    msg = json.dumps({
                        "type": "subscribe",
                        "assets_ids": list(self._subscribed_assets),
                    })
                    await self._ws.send(msg)
                    logger.info(
                        "ws_resubscribed", asset_ids=list(self._subscribed_assets)
                    )

            except (OSError, InvalidStatusCode) as exc:
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, _RECONNECT_MAX
                )
                logger.warning(
                    "ws_reconnect_failed",
                    error=str(exc),
                    next_delay=self._reconnect_delay,
                )
