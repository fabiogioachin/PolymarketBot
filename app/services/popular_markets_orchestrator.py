"""Popular markets orchestrator: snapshot top-N markets by 24h volume.

Uses the existing `PolymarketRestClient.list_markets(order="volume24hr", ...)`
to fetch the ranking, persists snapshots to SQLite (via `TradeStore`), and
keeps the latest snapshot in memory for the REST API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.clients.polymarket_rest import PolymarketRestClient
from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.intelligence import PopularMarket

logger = get_logger(__name__)


class PopularMarketsOrchestrator:
    """Snapshot top-N Polymarket markets by 24h volume on a slow cadence."""

    def __init__(
        self,
        *,
        rest_client: PolymarketRestClient | None = None,
        trade_store: Any = None,
    ) -> None:
        self._rest = rest_client or PolymarketRestClient()
        self._trade_store = trade_store
        self._last_tick: datetime | None = None
        self._last_snapshot: list[PopularMarket] = []

    @property
    def last_tick(self) -> datetime | None:
        return self._last_tick

    async def set_trade_store(self, store: Any) -> None:
        """Late-bind the TradeStore (pattern: IntelligenceOrchestrator)."""
        self._trade_store = store

    async def tick(self) -> list[PopularMarket]:
        """Fetch top-N markets by volume24h, snapshot, persist."""
        now = datetime.now(tz=UTC)
        cfg = app_config.intelligence.popular_markets
        top_n = int(cfg.top_n)

        try:
            markets = await self._rest.list_markets(
                active=True,
                closed=False,
                limit=top_n,
                order="volume24hr",
                ascending=False,
            )
        except Exception as exc:
            logger.warning("popular_markets_fetch_failed", error=str(exc))
            return list(self._last_snapshot)

        snapshot: list[PopularMarket] = []
        for m in markets:
            snapshot.append(
                PopularMarket(
                    market_id=m.id,
                    question=m.question,
                    volume24h=float(m.volume_24h or 0.0),
                    liquidity=float(m.liquidity) if m.liquidity is not None else None,
                    snapshot_time=now,
                )
            )

        self._last_snapshot = snapshot
        self._last_tick = now
        await self._persist(snapshot, now)
        logger.info("popular_markets_tick", count=len(snapshot))
        return snapshot

    async def _persist(
        self, snapshot: list[PopularMarket], now: datetime
    ) -> None:
        if self._trade_store is None or not snapshot:
            return
        try:
            rows = [
                {
                    "snapshot_time": now.timestamp(),
                    "market_id": pm.market_id,
                    "question": pm.question,
                    "volume24h": pm.volume24h,
                    "liquidity": pm.liquidity,
                }
                for pm in snapshot
            ]
            await self._trade_store.save_popular_market_snapshot(rows)
        except Exception as exc:
            logger.warning("popular_markets_persist_failed", error=str(exc))

    def get_popular_markets(self) -> list[PopularMarket]:
        """Return the latest in-memory snapshot."""
        return list(self._last_snapshot)
