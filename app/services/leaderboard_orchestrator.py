"""Leaderboard orchestrator: snapshot top traders by PnL on a slow cadence.

Uses the `PolymarketLeaderboardClient` to fetch the leaderboard, persists
snapshots to SQLite (via `TradeStore.save_leaderboard_snapshot`), and keeps
the latest snapshot in memory for the REST API.

Replicates the pattern of `PopularMarketsOrchestrator` (Phase 13 S2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.clients.polymarket_leaderboard import PolymarketLeaderboardClient
from app.core.logging import get_logger
from app.models.intelligence import LeaderboardEntry

logger = get_logger(__name__)


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first value whose key is in ``raw`` (even if falsy) or None."""
    for key in keys:
        if key in raw:
            return raw[key]
    return None


class LeaderboardOrchestrator:
    """Snapshot top Polymarket traders (by PnL) on a slow cadence."""

    def __init__(
        self,
        *,
        leaderboard_client: PolymarketLeaderboardClient | None = None,
        trade_store: Any = None,
    ) -> None:
        self._client = leaderboard_client or PolymarketLeaderboardClient()
        self._trade_store = trade_store
        self._last_tick: datetime | None = None
        self._last_snapshot: dict[str, list[LeaderboardEntry]] = {}

    @property
    def last_tick(self) -> datetime | None:
        return self._last_tick

    async def set_trade_store(self, store: Any) -> None:
        """Late-bind the TradeStore (pattern: PopularMarketsOrchestrator)."""
        self._trade_store = store

    async def tick(self, timeframe: str = "monthly") -> list[LeaderboardEntry]:
        """Fetch top traders for a timeframe, snapshot, persist."""
        now = datetime.now(tz=UTC)

        try:
            raw_rows = await self._client.fetch_leaderboard(
                timeframe=timeframe, limit=100
            )
        except Exception as exc:
            logger.warning(
                "leaderboard_fetch_failed", timeframe=timeframe, error=str(exc)
            )
            return list(self._last_snapshot.get(timeframe, []))

        try:
            snapshot: list[LeaderboardEntry] = []
            for idx, raw in enumerate(raw_rows):
                entry = self._parse_entry(raw, idx, timeframe, now)
                if entry is None:
                    continue
                snapshot.append(entry)

            self._last_snapshot[timeframe] = snapshot
            self._last_tick = now
            await self._persist(snapshot, timeframe, now)
            logger.info(
                "leaderboard_tick", timeframe=timeframe, count=len(snapshot)
            )
            return snapshot
        except Exception as exc:
            logger.warning(
                "leaderboard_fetch_failed", timeframe=timeframe, error=str(exc)
            )
            return list(self._last_snapshot.get(timeframe, []))

    def _parse_entry(
        self,
        raw: dict[str, Any],
        idx: int,
        timeframe: str,
        now: datetime,
    ) -> LeaderboardEntry | None:
        """Map a raw leaderboard row onto `LeaderboardEntry` defensively.

        Returns None if the row is malformed (missing wallet, non-castable pnl).
        """
        try:
            wallet_raw = _first_present(
                raw, ("wallet", "wallet_address", "address", "user", "taker")
            )
            wallet_address = (
                str(wallet_raw).lower() if wallet_raw is not None else ""
            )
            if not wallet_address:
                logger.warning(
                    "leaderboard_entry_parse_failed",
                    reason="missing_wallet",
                    raw_keys=list(raw.keys()),
                )
                return None

            pnl_raw = _first_present(
                raw, ("pnl", "pnl_usd", "profit", "total_pnl")
            )
            try:
                pnl_usd = float(pnl_raw) if pnl_raw is not None else 0.0
            except (TypeError, ValueError):
                logger.warning(
                    "leaderboard_entry_parse_failed",
                    reason="pnl_not_castable",
                    wallet=wallet_address,
                )
                return None

            rank_raw = _first_present(raw, ("rank", "position"))
            try:
                rank = int(rank_raw) if rank_raw is not None else idx + 1
            except (TypeError, ValueError):
                rank = idx + 1

            win_rate_raw = _first_present(raw, ("win_rate", "winRate"))
            if win_rate_raw is None:
                win_rate: float | None = None
            else:
                try:
                    win_rate = float(win_rate_raw)
                except (TypeError, ValueError):
                    win_rate = None

            return LeaderboardEntry(
                rank=rank,
                wallet_address=wallet_address,
                pnl_usd=pnl_usd,
                win_rate=win_rate,
                timeframe=timeframe,
                snapshot_time=now,
            )
        except Exception as exc:
            logger.warning(
                "leaderboard_entry_parse_failed", error=str(exc)
            )
            return None

    async def _persist(
        self,
        snapshot: list[LeaderboardEntry],
        timeframe: str,
        now: datetime,
    ) -> None:
        if self._trade_store is None or not snapshot:
            return
        try:
            rows = [
                {
                    "snapshot_time": now.timestamp(),
                    "rank": entry.rank,
                    "wallet_address": entry.wallet_address,
                    "pnl_usd": entry.pnl_usd,
                    "win_rate": entry.win_rate,
                    "timeframe": entry.timeframe,
                }
                for entry in snapshot
            ]
            await self._trade_store.save_leaderboard_snapshot(rows, timeframe)
        except Exception as exc:
            logger.warning(
                "leaderboard_persist_failed",
                timeframe=timeframe,
                error=str(exc),
            )

    def get_leaderboard(
        self, timeframe: str = "monthly"
    ) -> list[LeaderboardEntry]:
        """Return the latest in-memory snapshot for a timeframe."""
        return list(self._last_snapshot.get(timeframe, []))
