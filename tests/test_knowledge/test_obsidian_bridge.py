"""Tests for Obsidian Knowledge Graph bridge."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.knowledge.obsidian_bridge import ObsidianBridge, ObsidianNote, PatternNote

# -- Fixtures ------------------------------------------------------------------

OBSIDIAN_BASE = "http://127.0.0.1:27123"


def _note_json(
    *,
    content: str = "# Test Note\nSome content.",
    frontmatter: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "content": content,
        "frontmatter": frontmatter or {},
        "tags": tags or [],
    }


def _pattern_note_json(
    *,
    name: str = "election-surprise",
    domain: str = "politics",
    pattern_type: str = "reversal",
    confidence: float = 0.75,
    expected_outcome: str = "Price correction within 48h",
    last_triggered: str | None = None,
) -> dict[str, Any]:
    fm: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "type": pattern_type,
        "confidence": confidence,
        "expected_outcome": expected_outcome,
    }
    if last_triggered:
        fm["last_triggered"] = last_triggered
    return _note_json(
        content="Pattern description text here.",
        frontmatter=fm,
        tags=["pattern", domain],
    )


@pytest.fixture()
def bridge() -> ObsidianBridge:
    return ObsidianBridge()


# -- read_note -----------------------------------------------------------------


class TestReadNote:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_read_note(self, bridge: ObsidianBridge) -> None:
        respx.get(f"{OBSIDIAN_BASE}/vault/some/path.md").mock(
            return_value=httpx.Response(
                200,
                json=_note_json(
                    content="Hello world",
                    frontmatter={"title": "Test"},
                    tags=["test"],
                ),
            )
        )
        note = await bridge.read_note("some/path.md")
        await bridge.close()

        assert note is not None
        assert note.path == "some/path.md"
        assert note.content == "Hello world"
        assert note.frontmatter == {"title": "Test"}
        assert note.tags == ["test"]

    @respx.mock
    @pytest.mark.asyncio()
    async def test_read_note_not_found(self, bridge: ObsidianBridge) -> None:
        respx.get(f"{OBSIDIAN_BASE}/vault/missing.md").mock(
            return_value=httpx.Response(404)
        )
        note = await bridge.read_note("missing.md")
        await bridge.close()
        assert note is None

    @respx.mock
    @pytest.mark.asyncio()
    async def test_read_note_disabled(self, bridge: ObsidianBridge) -> None:
        bridge._enabled = False
        # No routes mocked — any HTTP call would raise
        note = await bridge.read_note("any/path.md")
        await bridge.close()
        assert note is None


# -- write_note ----------------------------------------------------------------


class TestWriteNote:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_write_note(self, bridge: ObsidianBridge) -> None:
        route = respx.put(f"{OBSIDIAN_BASE}/vault/test/note.md").mock(
            return_value=httpx.Response(200)
        )
        note = ObsidianNote(
            path="test/note.md",
            content="# Hello",
            frontmatter={"title": "Hello", "version": 1},
        )
        result = await bridge.write_note(note)
        await bridge.close()

        assert result is True
        assert route.called
        # Verify frontmatter is serialized into the content
        sent_body = route.calls[0].request.content.decode()
        assert sent_body.startswith("---\n")
        assert "title: Hello" in sent_body
        assert "# Hello" in sent_body

    @respx.mock
    @pytest.mark.asyncio()
    async def test_write_note_no_frontmatter(self, bridge: ObsidianBridge) -> None:
        route = respx.put(f"{OBSIDIAN_BASE}/vault/plain.md").mock(
            return_value=httpx.Response(200)
        )
        note = ObsidianNote(path="plain.md", content="Just content")
        result = await bridge.write_note(note)
        await bridge.close()

        assert result is True
        sent_body = route.calls[0].request.content.decode()
        assert sent_body == "Just content"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_write_note_disabled(self, bridge: ObsidianBridge) -> None:
        bridge._enabled = False
        result = await bridge.write_note(
            ObsidianNote(path="x.md", content="y")
        )
        await bridge.close()
        assert result is False


# -- search_notes --------------------------------------------------------------


class TestSearchNotes:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_search_notes(self, bridge: ObsidianBridge) -> None:
        expected = [
            {"filename": "note1.md", "matches": [{"match": {"content": "foo"}}]},
            {"filename": "note2.md", "matches": [{"match": {"content": "foo bar"}}]},
        ]
        respx.post(f"{OBSIDIAN_BASE}/search/simple/").mock(
            return_value=httpx.Response(200, json=expected)
        )
        results = await bridge.search_notes("foo")
        await bridge.close()

        assert len(results) == 2
        assert results[0]["filename"] == "note1.md"


# -- list_notes ----------------------------------------------------------------


class TestListNotes:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_list_notes(self, bridge: ObsidianBridge) -> None:
        respx.get(f"{OBSIDIAN_BASE}/vault/Knowledge/politics/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "files": [
                        {"path": "Knowledge/politics/note1.md"},
                        {"path": "Knowledge/politics/note2.md"},
                        {"path": "Knowledge/politics/image.png"},
                    ]
                },
            )
        )
        paths = await bridge.list_notes("Knowledge/politics")
        await bridge.close()

        assert len(paths) == 2
        assert "Knowledge/politics/note1.md" in paths
        assert "Knowledge/politics/note2.md" in paths

    @respx.mock
    @pytest.mark.asyncio()
    async def test_list_notes_folder_not_found(
        self, bridge: ObsidianBridge
    ) -> None:
        respx.get(f"{OBSIDIAN_BASE}/vault/nonexistent/").mock(
            return_value=httpx.Response(404)
        )
        paths = await bridge.list_notes("nonexistent")
        await bridge.close()
        assert paths == []


# -- read_patterns -------------------------------------------------------------


class TestReadPatterns:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_read_patterns(self, bridge: ObsidianBridge) -> None:
        patterns_folder = (
            f"{OBSIDIAN_BASE}/vault/"
            "Projects/PolymarketBot/patterns/politics/"
        )
        respx.get(patterns_folder).mock(
            return_value=httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "path": (
                                "Projects/PolymarketBot/patterns/"
                                "politics/election-surprise.md"
                            )
                        },
                    ]
                },
            )
        )
        note_path = (
            "Projects/PolymarketBot/patterns/politics/election-surprise.md"
        )
        respx.get(f"{OBSIDIAN_BASE}/vault/{note_path}").mock(
            return_value=httpx.Response(
                200,
                json=_pattern_note_json(
                    last_triggered="2026-03-15T10:00:00+00:00",
                ),
            )
        )

        patterns = await bridge.read_patterns("politics")
        await bridge.close()

        assert len(patterns) == 1
        p = patterns[0]
        assert isinstance(p, PatternNote)
        assert p.name == "election-surprise"
        assert p.domain == "politics"
        assert p.pattern_type == "reversal"
        assert p.confidence == 0.75
        assert p.expected_outcome == "Price correction within 48h"
        assert p.last_triggered is not None
        assert p.last_triggered.year == 2026
        assert "pattern" in p.tags


# -- write_market_analysis -----------------------------------------------------


class TestWriteMarketAnalysis:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_write_market_analysis(self, bridge: ObsidianBridge) -> None:
        route = respx.put(
            f"{OBSIDIAN_BASE}/vault/Projects/PolymarketBot/Markets/mkt-42.md"
        ).mock(return_value=httpx.Response(200))

        analysis = {
            "summary": "Strong value edge detected.",
            "risk_level": "medium",
            "strategy": "value_edge",
            "edge": "0.12",
            "notes": ["Liquidity adequate", "Expiry in 30 days"],
        }
        result = await bridge.write_market_analysis(
            market_id="mkt-42",
            question="Will event Z happen?",
            analysis=analysis,
        )
        await bridge.close()

        assert result is True
        assert route.called
        body = route.calls[0].request.content.decode()
        assert "market_id: mkt-42" in body
        assert "# Will event Z happen?" in body
        assert "Strong value edge detected." in body
        assert "**Risk Level**: medium" in body
        assert "- Liquidity adequate" in body


# -- update_pattern_confidence -------------------------------------------------


class TestUpdatePatternConfidence:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_update_pattern_confidence(
        self, bridge: ObsidianBridge
    ) -> None:
        pattern_path = "Projects/PolymarketBot/patterns/politics/test.md"
        # First: read the existing note
        respx.get(f"{OBSIDIAN_BASE}/vault/{pattern_path}").mock(
            return_value=httpx.Response(
                200,
                json=_pattern_note_json(confidence=0.5),
            )
        )
        # Then: write the updated note
        route = respx.put(f"{OBSIDIAN_BASE}/vault/{pattern_path}").mock(
            return_value=httpx.Response(200)
        )

        result = await bridge.update_pattern_confidence(pattern_path, 0.82)
        await bridge.close()

        assert result is True
        assert route.called
        body = route.calls[0].request.content.decode()
        assert "confidence: 0.82" in body
        assert "last_triggered:" in body

    @respx.mock
    @pytest.mark.asyncio()
    async def test_update_pattern_confidence_not_found(
        self, bridge: ObsidianBridge
    ) -> None:
        respx.get(f"{OBSIDIAN_BASE}/vault/missing/pattern.md").mock(
            return_value=httpx.Response(404)
        )
        result = await bridge.update_pattern_confidence("missing/pattern.md", 0.9)
        await bridge.close()
        assert result is False
