"""SQLite persistence for trade log and simulated positions.

Survives restarts. The execution engine reads on init and writes after each tick.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from app.core.logging import get_logger
from app.models.order import OrderSide, Position

logger = get_logger(__name__)

_DEFAULT_DB = Path("data/trades.db")

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    market_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,
    size_eur REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    edge REAL NOT NULL DEFAULT 0,
    pnl REAL NOT NULL DEFAULT 0,
    type TEXT NOT NULL DEFAULT 'open',
    reasoning TEXT NOT NULL DEFAULT '',
    time_horizon TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    token_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT 'BUY',
    size REAL NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    current_price REAL NOT NULL DEFAULT 0
)
"""

_CREATE_STATE = """
CREATE TABLE IF NOT EXISTS engine_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_INTELLIGENCE_EVENTS = """
CREATE TABLE IF NOT EXISTS intelligence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    total_anomalies INTEGER DEFAULT 0,
    events_json TEXT DEFAULT '[]',
    news_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_WHALE_TRADES = """
CREATE TABLE IF NOT EXISTS whale_trades (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    market_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    side TEXT NOT NULL,
    size_usd REAL NOT NULL,
    price REAL NOT NULL,
    is_pre_resolution INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    wallet_total_pnl REAL,
    wallet_weekly_pnl REAL,
    wallet_volume_rank INTEGER
)
"""

_CREATE_WHALE_TRADES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_whale_trades_market "
    "ON whale_trades(market_id, timestamp)"
)

_CREATE_POPULAR_MARKETS = """
CREATE TABLE IF NOT EXISTS popular_markets_snapshot (
    snapshot_time REAL NOT NULL,
    market_id TEXT NOT NULL,
    question TEXT DEFAULT '',
    volume24h REAL NOT NULL,
    liquidity REAL,
    PRIMARY KEY (snapshot_time, market_id)
)
"""

_CREATE_LEADERBOARD = """
CREATE TABLE IF NOT EXISTS trader_leaderboard (
    snapshot_time REAL NOT NULL,
    rank INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    pnl_usd REAL NOT NULL,
    win_rate REAL,
    timeframe TEXT NOT NULL,
    PRIMARY KEY (snapshot_time, wallet_address, timeframe)
)
"""


class TradeStore:
    """Async SQLite store for trades and positions."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_CREATE_TRADES)
        await self._conn.execute(_CREATE_POSITIONS)
        await self._conn.execute(_CREATE_STATE)
        await self._conn.execute(_CREATE_INTELLIGENCE_EVENTS)
        await self._conn.execute(_CREATE_WHALE_TRADES)
        await self._conn.execute(_CREATE_WHALE_TRADES_INDEX)
        await self._conn.execute(_CREATE_POPULAR_MARKETS)
        await self._conn.execute(_CREATE_LEADERBOARD)
        await self._conn.commit()
        # Migration: add time_horizon column to existing DBs
        try:
            await self._conn.execute(
                "ALTER TABLE trades ADD COLUMN time_horizon TEXT NOT NULL DEFAULT ''"
            )
            await self._conn.commit()
        except Exception:
            logger.debug("time_horizon_column_already_exists")  # migration already applied
        logger.info("trade_store_initialized", path=self._db_path)

    def _ensure(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "TradeStore not initialized"
            raise RuntimeError(msg)
        return self._conn

    # ── Trades ───────────────────────────────────────────────────────

    async def append_trade(self, trade: dict[str, object]) -> None:
        conn = self._ensure()
        await conn.execute(
            """INSERT INTO trades (timestamp, market_id, strategy, side, size_eur,
               price, edge, pnl, type, reasoning, time_horizon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(trade.get("timestamp", "")),
                str(trade.get("market_id", "")),
                str(trade.get("strategy", "")),
                str(trade.get("side", "")),
                float(trade.get("size_eur", 0) or 0),
                float(trade.get("price", 0) or 0),
                float(trade.get("edge", 0) or 0),
                float(trade.get("pnl", 0) or 0),
                str(trade.get("type", "open")),
                str(trade.get("reasoning", "")),
                str(trade.get("horizon", "")),
            ),
        )
        await conn.commit()

    async def get_trades(self, limit: int = 500) -> list[dict[str, object]]:
        conn = self._ensure()
        cursor = await conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [
            {
                "timestamp": row["timestamp"],
                "market_id": row["market_id"],
                "strategy": row["strategy"],
                "side": row["side"],
                "size_eur": row["size_eur"],
                "price": row["price"],
                "edge": row["edge"],
                "pnl": row["pnl"],
                "type": row["type"],
                "reasoning": row["reasoning"],
                "time_horizon": row["time_horizon"],
            }
            for row in rows
        ]

    async def get_trade_count(self) -> int:
        conn = self._ensure()
        cursor = await conn.execute("SELECT COUNT(*) FROM trades")
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Positions ────────────────────────────────────────────────────

    async def save_positions(self, positions: list[Position]) -> None:
        conn = self._ensure()
        await conn.execute("DELETE FROM positions")
        for pos in positions:
            await conn.execute(
                """INSERT OR REPLACE INTO positions
                   (token_id, market_id, side, size, avg_price, current_price)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    pos.token_id,
                    pos.market_id,
                    str(pos.side),
                    pos.size,
                    pos.avg_price,
                    pos.current_price,
                ),
            )
        await conn.commit()

    async def load_positions(self) -> list[Position]:
        conn = self._ensure()
        cursor = await conn.execute("SELECT * FROM positions")
        rows = await cursor.fetchall()
        return [
            Position(
                token_id=row["token_id"],
                market_id=row["market_id"],
                side=OrderSide(row["side"]),
                size=row["size"],
                avg_price=row["avg_price"],
                current_price=row["current_price"],
            )
            for row in rows
        ]

    # ── Engine state (balance, tick count, etc.) ─────────────────────

    async def save_state(self, key: str, value: str) -> None:
        conn = self._ensure()
        await conn.execute(
            "INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        await conn.commit()

    async def load_state(self, key: str, default: str = "") -> str:
        conn = self._ensure()
        cursor = await conn.execute(
            "SELECT value FROM engine_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else default

    # ── Intelligence events ────────────────────────────────────────────

    async def save_anomaly_report(self, report: dict[str, object]) -> None:
        """Persist an anomaly report from the intelligence pipeline."""
        conn = self._ensure()
        await conn.execute(
            """INSERT INTO intelligence_events
               (detected_at, total_anomalies, events_json, news_json)
               VALUES (?, ?, ?, ?)""",
            (
                str(report.get("detected_at", "")),
                int(report.get("total_anomalies", 0)),
                str(report.get("events_json", "[]")),
                str(report.get("news_json", "[]")),
            ),
        )
        await conn.commit()

    async def load_anomaly_reports(self, limit: int = 100) -> list[dict[str, object]]:
        """Load recent anomaly reports, newest first."""
        conn = self._ensure()
        cursor = await conn.execute(
            "SELECT * FROM intelligence_events ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "detected_at": row["detected_at"],
                "total_anomalies": row["total_anomalies"],
                "events_json": row["events_json"],
                "news_json": row["news_json"],
            }
            for row in rows
        ]

    # ── Whale trades (Phase 13 S2) ────────────────────────────────────

    async def save_whale_trade(self, trade: dict[str, object]) -> None:
        """Persist a single whale trade (INSERT OR REPLACE on `id`).

        Expected dict keys match column names (lesson 2026-04-15): id,
        timestamp, market_id, wallet_address, side, size_usd, price,
        is_pre_resolution, raw_json, wallet_total_pnl, wallet_weekly_pnl,
        wallet_volume_rank.
        """
        conn = self._ensure()
        await conn.execute(
            """INSERT OR REPLACE INTO whale_trades (
                id, timestamp, market_id, wallet_address, side, size_usd,
                price, is_pre_resolution, raw_json, wallet_total_pnl,
                wallet_weekly_pnl, wallet_volume_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(trade.get("id", "")),
                float(trade.get("timestamp", 0.0) or 0.0),
                str(trade.get("market_id", "")),
                str(trade.get("wallet_address", "")),
                str(trade.get("side", "")),
                float(trade.get("size_usd", 0.0) or 0.0),
                float(trade.get("price", 0.0) or 0.0),
                int(trade.get("is_pre_resolution", 0) or 0),
                str(trade.get("raw_json", "") or ""),
                trade.get("wallet_total_pnl"),
                trade.get("wallet_weekly_pnl"),
                trade.get("wallet_volume_rank"),
            ),
        )
        await conn.commit()

    async def load_whale_trades(
        self, market_id: str, since_ts: float
    ) -> list[dict[str, object]]:
        """Return whale trades for `market_id` with timestamp >= since_ts."""
        conn = self._ensure()
        cursor = await conn.execute(
            """SELECT id, timestamp, market_id, wallet_address, side,
                      size_usd, price, is_pre_resolution, raw_json,
                      wallet_total_pnl, wallet_weekly_pnl, wallet_volume_rank
               FROM whale_trades
               WHERE market_id = ? AND timestamp >= ?
               ORDER BY timestamp DESC""",
            (market_id, float(since_ts)),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "market_id": row["market_id"],
                "wallet_address": row["wallet_address"],
                "side": row["side"],
                "size_usd": row["size_usd"],
                "price": row["price"],
                "is_pre_resolution": row["is_pre_resolution"],
                "raw_json": row["raw_json"],
                "wallet_total_pnl": row["wallet_total_pnl"],
                "wallet_weekly_pnl": row["wallet_weekly_pnl"],
                "wallet_volume_rank": row["wallet_volume_rank"],
            }
            for row in rows
        ]

    # ── Popular markets snapshot ──────────────────────────────────────

    async def save_popular_market_snapshot(
        self, rows: list[dict[str, object]]
    ) -> None:
        """Bulk-insert a popular-markets snapshot (idempotent by PK)."""
        if not rows:
            return
        conn = self._ensure()
        for row in rows:
            await conn.execute(
                """INSERT OR REPLACE INTO popular_markets_snapshot
                   (snapshot_time, market_id, question, volume24h, liquidity)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    float(row.get("snapshot_time", 0.0) or 0.0),
                    str(row.get("market_id", "")),
                    str(row.get("question", "") or ""),
                    float(row.get("volume24h", 0.0) or 0.0),
                    row.get("liquidity"),
                ),
            )
        await conn.commit()

    async def load_latest_popular_markets(
        self, limit: int = 20
    ) -> list[dict[str, object]]:
        """Return rows from the most recent popular-markets snapshot."""
        conn = self._ensure()
        cursor = await conn.execute(
            "SELECT MAX(snapshot_time) AS ts FROM popular_markets_snapshot"
        )
        row = await cursor.fetchone()
        if not row or row["ts"] is None:
            return []
        latest_ts = float(row["ts"])
        cursor = await conn.execute(
            """SELECT snapshot_time, market_id, question, volume24h, liquidity
               FROM popular_markets_snapshot
               WHERE snapshot_time = ?
               ORDER BY volume24h DESC LIMIT ?""",
            (latest_ts, int(limit)),
        )
        rows = await cursor.fetchall()
        return [
            {
                "snapshot_time": r["snapshot_time"],
                "market_id": r["market_id"],
                "question": r["question"],
                "volume24h": r["volume24h"],
                "liquidity": r["liquidity"],
            }
            for r in rows
        ]

    # ── Trader leaderboard ────────────────────────────────────────────

    async def save_leaderboard_snapshot(
        self, rows: list[dict[str, object]], timeframe: str
    ) -> None:
        """Persist a leaderboard snapshot for a given timeframe."""
        if not rows:
            return
        conn = self._ensure()
        for row in rows:
            await conn.execute(
                """INSERT OR REPLACE INTO trader_leaderboard
                   (snapshot_time, rank, wallet_address, pnl_usd, win_rate,
                    timeframe)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    float(row.get("snapshot_time", 0.0) or 0.0),
                    int(row.get("rank", 0) or 0),
                    str(row.get("wallet_address", "")),
                    float(row.get("pnl_usd", 0.0) or 0.0),
                    row.get("win_rate"),
                    str(row.get("timeframe", timeframe)),
                ),
            )
        await conn.commit()

    async def load_latest_leaderboard(
        self, timeframe: str, limit: int = 100
    ) -> list[dict[str, object]]:
        """Return rows from the most recent leaderboard snapshot for a tf."""
        conn = self._ensure()
        cursor = await conn.execute(
            """SELECT MAX(snapshot_time) AS ts FROM trader_leaderboard
               WHERE timeframe = ?""",
            (timeframe,),
        )
        row = await cursor.fetchone()
        if not row or row["ts"] is None:
            return []
        latest_ts = float(row["ts"])
        cursor = await conn.execute(
            """SELECT snapshot_time, rank, wallet_address, pnl_usd, win_rate,
                      timeframe
               FROM trader_leaderboard
               WHERE timeframe = ? AND snapshot_time = ?
               ORDER BY rank ASC LIMIT ?""",
            (timeframe, latest_ts, int(limit)),
        )
        rows = await cursor.fetchall()
        return [
            {
                "snapshot_time": r["snapshot_time"],
                "rank": r["rank"],
                "wallet_address": r["wallet_address"],
                "pnl_usd": r["pnl_usd"],
                "win_rate": r["win_rate"],
                "timeframe": r["timeframe"],
            }
            for r in rows
        ]

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
