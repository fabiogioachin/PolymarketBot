"""Risk/Strategy Knowledge Base: structured storage for market risk analysis."""

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import aiosqlite
from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_DB_PATH = Path("data/risk_kb.db")


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MarketKnowledge(BaseModel):
    """Complete knowledge record for a tracked market."""

    market_id: str
    rule_analysis: dict = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_reason: str = ""
    strategy_applied: str = ""
    strategy_params: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    resolution_outcome: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS market_knowledge (
    market_id TEXT PRIMARY KEY,
    rule_analysis TEXT DEFAULT '{}',
    risk_level TEXT DEFAULT 'medium',
    risk_reason TEXT DEFAULT '',
    strategy_applied TEXT DEFAULT '',
    strategy_params TEXT DEFAULT '{}',
    notes TEXT DEFAULT '[]',
    resolution_outcome TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""

_UPSERT_SQL = """
INSERT INTO market_knowledge
    (market_id, rule_analysis, risk_level, risk_reason, strategy_applied,
     strategy_params, notes, resolution_outcome, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, ?), ?)
ON CONFLICT(market_id) DO UPDATE SET
    rule_analysis=excluded.rule_analysis,
    risk_level=excluded.risk_level,
    risk_reason=excluded.risk_reason,
    strategy_applied=excluded.strategy_applied,
    strategy_params=excluded.strategy_params,
    notes=excluded.notes,
    resolution_outcome=excluded.resolution_outcome,
    updated_at=excluded.updated_at
"""


class RiskKnowledgeBase:
    """SQLite-backed knowledge base for market risk and strategy tracking."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            msg = "Database not initialized. Call init() first."
            raise RuntimeError(msg)
        return self._db

    async def init(self) -> None:
        """Initialize database and create tables."""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        logger.info("risk_kb_initialized", db_path=self._db_path)

    async def upsert(self, knowledge: MarketKnowledge) -> None:
        """Insert or update a market knowledge record."""
        db = self._ensure_db()
        now = datetime.now(tz=UTC).isoformat()
        await db.execute(
            _UPSERT_SQL,
            (
                knowledge.market_id,
                json.dumps(knowledge.rule_analysis),
                knowledge.risk_level.value,
                knowledge.risk_reason,
                knowledge.strategy_applied,
                json.dumps(knowledge.strategy_params),
                json.dumps(knowledge.notes),
                knowledge.resolution_outcome,
                knowledge.created_at.isoformat() if knowledge.created_at else now,
                now,
                now,
            ),
        )
        await db.commit()

    async def get(self, market_id: str) -> MarketKnowledge | None:
        """Get knowledge for a specific market."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM market_knowledge WHERE market_id = ?", (market_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_model(row)

    async def get_all(self) -> list[MarketKnowledge]:
        """Get all market knowledge records."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM market_knowledge ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_by_risk_level(self, level: RiskLevel) -> list[MarketKnowledge]:
        """Get all markets with a specific risk level."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM market_knowledge WHERE risk_level = ? ORDER BY updated_at DESC",
            (level.value,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_by_strategy(self, strategy: str) -> list[MarketKnowledge]:
        """Get all markets using a specific strategy."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM market_knowledge WHERE strategy_applied = ? "
            "ORDER BY updated_at DESC",
            (strategy,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def add_note(self, market_id: str, note: str) -> bool:
        """Add a note to a market's knowledge record. Returns False if not found."""
        existing = await self.get(market_id)
        if existing is None:
            return False
        existing.notes.append(note)
        await self.upsert(existing)
        return True

    async def update_resolution(self, market_id: str, outcome: str) -> bool:
        """Record how a market resolved. Returns False if not found."""
        existing = await self.get(market_id)
        if existing is None:
            return False
        existing.resolution_outcome = outcome
        await self.upsert(existing)
        return True

    async def delete(self, market_id: str) -> bool:
        """Delete a market knowledge record."""
        db = self._ensure_db()
        cursor = await db.execute(
            "DELETE FROM market_knowledge WHERE market_id = ?", (market_id,)
        )
        await db.commit()
        return cursor.rowcount > 0

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @staticmethod
    def _row_to_model(row: aiosqlite.Row) -> MarketKnowledge:
        """Convert a database row to a MarketKnowledge model."""
        return MarketKnowledge(
            market_id=row["market_id"],
            rule_analysis=json.loads(row["rule_analysis"]),
            risk_level=RiskLevel(row["risk_level"]),
            risk_reason=row["risk_reason"],
            strategy_applied=row["strategy_applied"],
            strategy_params=json.loads(row["strategy_params"]),
            notes=json.loads(row["notes"]),
            resolution_outcome=row["resolution_outcome"],
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            ),
            updated_at=(
                datetime.fromisoformat(row["updated_at"])
                if row["updated_at"]
                else None
            ),
        )
