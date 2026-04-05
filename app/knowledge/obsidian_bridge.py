"""Obsidian KG bridge: bidirectional sync between bot and Obsidian vault."""

import contextlib
from datetime import UTC, datetime

import httpx
import yaml
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.core.yaml_config import app_config

logger = get_logger(__name__)


class ObsidianNote(BaseModel):
    """Representation of an Obsidian note."""

    path: str  # e.g., "Projects/PolymarketBot/Markets/market-123.md"
    content: str = ""
    frontmatter: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class PatternNote(BaseModel):
    """A pattern read from the Knowledge Graph."""

    path: str
    name: str = ""
    domain: str = ""
    pattern_type: str = ""
    confidence: float = 0.0
    last_triggered: datetime | None = None
    description: str = ""
    expected_outcome: str = ""
    tags: list[str] = Field(default_factory=list)


class ObsidianBridge:
    """Bridge between the bot and Obsidian Knowledge Graph via REST API."""

    def __init__(self) -> None:
        self._base_url = settings.obsidian.api_url
        self._api_key = settings.obsidian.api_key
        self._enabled = app_config.intelligence.obsidian.enabled
        self._patterns_path = app_config.intelligence.obsidian.patterns_path
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
        return self._client

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def read_note(self, path: str) -> ObsidianNote | None:
        """Read a note from the vault."""
        if not self._enabled:
            return None
        try:
            resp = await self._get_client().get(
                f"/vault/{path}",
                headers={"Accept": "application/vnd.olrapi.note+json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return ObsidianNote(
                path=path,
                content=data.get("content", ""),
                frontmatter=data.get("frontmatter", {}),
                tags=data.get("tags", []),
            )
        except httpx.RequestError as exc:
            logger.warning("obsidian_read_failed", path=path, error=str(exc))
            return None

    async def write_note(self, note: ObsidianNote) -> bool:
        """Write or update a note in the vault."""
        if not self._enabled:
            return False
        try:
            content = note.content
            if note.frontmatter:
                fm = yaml.dump(
                    note.frontmatter, default_flow_style=False, allow_unicode=True
                )
                content = f"---\n{fm}---\n\n{content}"

            resp = await self._get_client().put(
                f"/vault/{note.path}",
                content=content,
                headers={"Content-Type": "text/markdown"},
            )
            resp.raise_for_status()
            logger.info("obsidian_note_written", path=note.path)
            return True
        except httpx.RequestError as exc:
            logger.warning("obsidian_write_failed", path=note.path, error=str(exc))
            return False

    async def search_notes(self, query: str, context_length: int = 100) -> list[dict]:
        """Search notes in the vault."""
        if not self._enabled:
            return []
        try:
            resp = await self._get_client().post(
                "/search/simple/",
                json={"query": query, "contextLength": context_length},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as exc:
            logger.warning("obsidian_search_failed", query=query, error=str(exc))
            return []

    async def list_notes(self, folder: str) -> list[str]:
        """List note paths in a folder."""
        if not self._enabled:
            return []
        try:
            resp = await self._get_client().get(f"/vault/{folder}/")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return [
                f.get("path", "")
                for f in data.get("files", [])
                if f.get("path", "").endswith(".md")
            ]
        except httpx.RequestError as exc:
            logger.warning("obsidian_list_failed", folder=folder, error=str(exc))
            return []

    # -- Domain-specific operations -----------------------------------------------

    async def read_patterns(self, domain: str) -> list[PatternNote]:
        """Read active patterns for a domain from the Knowledge Graph."""
        folder = f"{self._patterns_path}/{domain}"
        paths = await self.list_notes(folder)

        patterns: list[PatternNote] = []
        for path in paths:
            note = await self.read_note(path)
            if note is None:
                continue
            pattern = PatternNote(
                path=path,
                name=note.frontmatter.get(
                    "name", path.split("/")[-1].replace(".md", "")
                ),
                domain=note.frontmatter.get("domain", domain),
                pattern_type=note.frontmatter.get("type", ""),
                confidence=float(note.frontmatter.get("confidence", 0.5)),
                description=note.content[:500] if note.content else "",
                expected_outcome=note.frontmatter.get("expected_outcome", ""),
                tags=note.tags,
            )
            if note.frontmatter.get("last_triggered"):
                with contextlib.suppress(ValueError, TypeError):
                    pattern.last_triggered = datetime.fromisoformat(
                        note.frontmatter["last_triggered"]
                    )
            patterns.append(pattern)

        logger.info("patterns_loaded", domain=domain, count=len(patterns))
        return patterns

    async def write_market_analysis(
        self,
        market_id: str,
        question: str,
        analysis: dict,
    ) -> bool:
        """Write a market analysis to the Projects zone."""
        path = f"Projects/PolymarketBot/Markets/{market_id}.md"
        now = datetime.now(tz=UTC)

        frontmatter = {
            "market_id": market_id,
            "type": "market_analysis",
            "created": now.isoformat(),
            "updated": now.isoformat(),
            **analysis.get("frontmatter", {}),
        }

        content = f"# {question}\n\n"
        if "summary" in analysis:
            content += f"## Summary\n{analysis['summary']}\n\n"
        if "risk_level" in analysis:
            content += f"**Risk Level**: {analysis['risk_level']}\n"
        if "strategy" in analysis:
            content += f"**Strategy**: {analysis['strategy']}\n"
        if "edge" in analysis:
            content += f"**Edge**: {analysis['edge']}\n"
        if "notes" in analysis:
            content += "\n## Notes\n"
            for note_text in analysis["notes"]:
                content += f"- {note_text}\n"

        return await self.write_note(
            ObsidianNote(
                path=path,
                content=content,
                frontmatter=frontmatter,
            )
        )

    async def update_pattern_confidence(
        self, pattern_path: str, new_confidence: float
    ) -> bool:
        """Update a pattern's confidence after validation."""
        note = await self.read_note(pattern_path)
        if note is None:
            return False

        note.frontmatter["confidence"] = round(new_confidence, 3)
        note.frontmatter["last_triggered"] = datetime.now(tz=UTC).isoformat()
        return await self.write_note(note)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
