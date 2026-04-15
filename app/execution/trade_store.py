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

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
