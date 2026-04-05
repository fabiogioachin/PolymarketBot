"""SQLite database for market resolution storage."""

from __future__ import annotations

import contextlib
from pathlib import Path

import aiosqlite

from app.core.logging import get_logger
from app.models.valuation import MarketResolution

logger = get_logger(__name__)

_DEFAULT_DB_PATH = Path("data/resolutions.db")

_MIGRATE_ADD_SOURCE = (
    "ALTER TABLE market_resolutions"
    " ADD COLUMN source TEXT NOT NULL DEFAULT 'polymarket'"
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS market_resolutions (
    market_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    final_price REAL NOT NULL DEFAULT 0.0,
    resolved_yes INTEGER NOT NULL DEFAULT 0,
    resolution_date TEXT,
    volume REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'polymarket'
)
"""


class ResolutionDB:
    """Async SQLite store for market resolution history."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database and create tables if needed."""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_CREATE_TABLE)
        # Migrate: add source column if missing (for existing DBs)
        with contextlib.suppress(Exception):
            await self._conn.execute(_MIGRATE_ADD_SOURCE)
        await self._conn.commit()
        logger.info("resolution_db_initialized", path=self._db_path)

    def _ensure_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "Database not initialized. Call init() first."
            raise RuntimeError(msg)
        return self._conn

    async def add_resolution(self, resolution: MarketResolution) -> None:
        """Insert or replace a market resolution record."""
        conn = self._ensure_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO market_resolutions
                (market_id, category, question, final_price, resolved_yes,
                 resolution_date, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolution.market_id,
                resolution.category,
                resolution.question,
                resolution.final_price,
                int(resolution.resolved_yes),
                resolution.resolution_date.isoformat() if resolution.resolution_date else None,
                resolution.volume,
                resolution.source,
            ),
        )
        await conn.commit()

    async def get_resolutions(
        self, category: str | None = None, source: str | None = None
    ) -> list[MarketResolution]:
        """Retrieve resolution records, optionally filtered by category and/or source."""
        conn = self._ensure_conn()
        conditions: list[str] = []
        params: list[str] = []
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        query = "SELECT * FROM market_resolutions"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_resolution(row) for row in rows]

    async def get_resolution(self, market_id: str) -> MarketResolution | None:
        """Retrieve a single resolution by market ID."""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM market_resolutions WHERE market_id = ?",
            (market_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_resolution(row)

    async def get_resolution_count(self, category: str | None = None) -> int:
        """Count resolution records, optionally filtered by category."""
        conn = self._ensure_conn()
        if category is not None:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM market_resolutions WHERE category = ?",
                (category,),
            )
        else:
            cursor = await conn.execute("SELECT COUNT(*) FROM market_resolutions")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("resolution_db_closed")

    @staticmethod
    def _row_to_resolution(row: aiosqlite.Row) -> MarketResolution:
        from datetime import datetime

        resolution_date = None
        if row["resolution_date"]:
            resolution_date = datetime.fromisoformat(row["resolution_date"])
        return MarketResolution(
            market_id=row["market_id"],
            category=row["category"],
            question=row["question"],
            final_price=row["final_price"],
            resolved_yes=bool(row["resolved_yes"]),
            resolution_date=resolution_date,
            volume=row["volume"],
            source=row["source"] if "source" in dict(row) else "polymarket",
        )
