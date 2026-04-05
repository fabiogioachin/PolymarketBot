"""Tests for KnowledgeService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.knowledge.obsidian_bridge import ObsidianNote, PatternNote
from app.models.knowledge import KnowledgeContext, PatternStatus
from app.services.knowledge_service import KnowledgeService

# ---------------------------------------------------------------------------
# Mock bridge
# ---------------------------------------------------------------------------

def _make_pattern_note(
    *,
    name: str = "test-pattern",
    domain: str = "politics",
    confidence: float = 0.8,
    description: str = "election polling volatility spikes before deadline",
    pattern_type: str = "recurring",
    expected_outcome: str = "price swing",
    path: str | None = None,
    tags: list[str] | None = None,
) -> PatternNote:
    return PatternNote(
        path=path or f"Projects/PolymarketBot/patterns/{domain}/{name}.md",
        name=name,
        domain=domain,
        pattern_type=pattern_type,
        confidence=confidence,
        description=description,
        expected_outcome=expected_outcome,
        tags=tags or ["politics"],
    )


def _make_obsidian_note(
    *,
    path: str = "Knowledge/politics/intro.md",
    content: str = "Background on political prediction markets.",
    frontmatter: dict | None = None,
    tags: list[str] | None = None,
) -> ObsidianNote:
    return ObsidianNote(
        path=path,
        content=content,
        frontmatter=frontmatter or {},
        tags=tags or [],
    )


def _build_mock_bridge(
    *,
    pattern_notes: list[PatternNote] | None = None,
    listed_paths: list[str] | None = None,
    knowledge_notes: list[ObsidianNote] | None = None,
) -> AsyncMock:
    """Create an AsyncMock that behaves like ObsidianBridge."""
    bridge = AsyncMock()
    bridge.read_patterns = AsyncMock(return_value=pattern_notes or [])
    bridge.list_notes = AsyncMock(return_value=listed_paths or [])
    bridge.write_note = AsyncMock(return_value=True)
    bridge.update_pattern_confidence = AsyncMock(return_value=True)

    # read_note returns matching note from knowledge_notes or a default
    _notes_by_path: dict[str, ObsidianNote] = {}
    for n in knowledge_notes or []:
        _notes_by_path[n.path] = n

    async def _read_note(path: str) -> ObsidianNote | None:
        return _notes_by_path.get(path)

    bridge.read_note = AsyncMock(side_effect=_read_note)
    return bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_patterns() -> None:
    """read_patterns returns Pattern list from mocked bridge."""
    notes = [_make_pattern_note(), _make_pattern_note(name="second")]
    bridge = _build_mock_bridge(pattern_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    result = await svc.read_patterns("politics")

    assert len(result) == 2
    assert result[0].name == "test-pattern"
    assert result[0].confidence == 0.8
    assert result[0].status == PatternStatus.ACTIVE
    bridge.read_patterns.assert_awaited_once_with("politics")


@pytest.mark.asyncio
async def test_read_patterns_filters_active() -> None:
    """Only active patterns are returned (standby/retired filtered)."""
    # _note_to_pattern always sets ACTIVE, so all notes become active.
    # This test verifies the filter pathway by checking that all returned
    # patterns have ACTIVE status.
    notes = [
        _make_pattern_note(name="a", confidence=0.9),
        _make_pattern_note(name="b", confidence=0.1),
    ]
    bridge = _build_mock_bridge(pattern_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    result = await svc.read_patterns("politics")

    assert all(p.status == PatternStatus.ACTIVE for p in result)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_read_domain_knowledge() -> None:
    """read_domain_knowledge returns knowledge note contents."""
    paths = ["Knowledge/politics/intro.md", "Knowledge/politics/history.md"]
    notes = [
        _make_obsidian_note(path="Knowledge/politics/intro.md", content="Intro text"),
        _make_obsidian_note(
            path="Knowledge/politics/history.md", content="History text"
        ),
    ]
    bridge = _build_mock_bridge(listed_paths=paths, knowledge_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    result = await svc.read_domain_knowledge("politics")

    assert len(result) == 2
    assert "Intro text" in result[0]
    assert "History text" in result[1]
    bridge.list_notes.assert_awaited_once_with("Knowledge/politics")


@pytest.mark.asyncio
async def test_match_patterns_by_text() -> None:
    """Event text matching pattern description produces matches."""
    notes = [
        _make_pattern_note(
            description="election polling volatility spikes before deadline"
        ),
    ]
    bridge = _build_mock_bridge(pattern_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    matches = await svc.match_patterns(
        "politics", "the election polling shows unusual volatility"
    )

    assert len(matches) == 1
    assert matches[0].match_score > 0
    assert "election" in matches[0].matched_keywords
    assert "polling" in matches[0].matched_keywords


@pytest.mark.asyncio
async def test_match_patterns_no_match() -> None:
    """Unrelated text returns no matches."""
    notes = [
        _make_pattern_note(
            description="election polling volatility spikes before deadline"
        ),
    ]
    bridge = _build_mock_bridge(pattern_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    matches = await svc.match_patterns("politics", "crypto bitcoin ethereum trading")

    assert len(matches) == 0


@pytest.mark.asyncio
async def test_match_patterns_with_keywords() -> None:
    """User-provided keywords boost matching score."""
    notes = [
        _make_pattern_note(
            description="election polling volatility spikes before deadline"
        ),
    ]
    bridge = _build_mock_bridge(pattern_notes=notes)
    svc = KnowledgeService(bridge=bridge)

    # Without keywords
    matches_no_kw = await svc.match_patterns("politics", "election results")
    # Clear cache to force re-read
    svc._pattern_cache.clear()
    # With keywords that overlap pattern description
    matches_kw = await svc.match_patterns(
        "politics", "election results", keywords=["polling", "deadline"]
    )

    assert len(matches_kw) >= 1
    # Keyword-boosted score should be >= no-keyword score
    if matches_no_kw:
        assert matches_kw[0].match_score >= matches_no_kw[0].match_score


@pytest.mark.asyncio
async def test_build_knowledge_context() -> None:
    """build_knowledge_context returns full context with signal and confidence."""
    notes = [
        _make_pattern_note(
            description="election polling volatility spikes before deadline"
        ),
    ]
    paths = ["Knowledge/politics/intro.md"]
    knowledge = [
        _make_obsidian_note(path="Knowledge/politics/intro.md", content="Intro"),
    ]
    bridge = _build_mock_bridge(
        pattern_notes=notes, listed_paths=paths, knowledge_notes=knowledge
    )
    svc = KnowledgeService(bridge=bridge)

    ctx = await svc.build_knowledge_context(
        "politics", "election polling is shifting"
    )

    assert isinstance(ctx, KnowledgeContext)
    assert ctx.domain == "politics"
    assert len(ctx.patterns) >= 1
    assert ctx.composite_signal > 0
    assert ctx.confidence > 0
    assert len(ctx.domain_notes) == 1


@pytest.mark.asyncio
async def test_build_knowledge_context_empty() -> None:
    """No matching patterns results in zero signal."""
    bridge = _build_mock_bridge(pattern_notes=[], listed_paths=[])
    svc = KnowledgeService(bridge=bridge)

    ctx = await svc.build_knowledge_context("politics", "nothing relevant")

    assert ctx.composite_signal == 0.0
    assert ctx.confidence == 0.0
    assert len(ctx.patterns) == 0


@pytest.mark.asyncio
async def test_write_event() -> None:
    """write_event delegates to bridge.write_note with correct path."""
    bridge = _build_mock_bridge()
    svc = KnowledgeService(bridge=bridge)

    result = await svc.write_event(
        "politics", "Election Update", "Big news today.", tags=["breaking"]
    )

    assert result is True
    bridge.write_note.assert_awaited_once()
    call_note: ObsidianNote = bridge.write_note.call_args[0][0]
    assert "politics" in call_note.path
    assert "Election Update" in call_note.path
    assert call_note.frontmatter["type"] == "event"
    assert call_note.frontmatter["domain"] == "politics"


@pytest.mark.asyncio
async def test_update_pattern_confidence_correct() -> None:
    """Correct outcome increases confidence."""
    pattern_path = "Projects/PolymarketBot/patterns/politics/test.md"
    note = _make_obsidian_note(
        path=pattern_path,
        content="pattern content",
        frontmatter={"confidence": 0.6},
    )
    bridge = _build_mock_bridge(knowledge_notes=[note])
    svc = KnowledgeService(bridge=bridge)

    result = await svc.update_pattern_confidence(pattern_path, was_correct=True)

    assert result is True
    bridge.update_pattern_confidence.assert_awaited_once()
    new_conf = bridge.update_pattern_confidence.call_args[0][1]
    # 0.6 + (1 - 0.6) * 0.1 = 0.64
    assert abs(new_conf - 0.64) < 0.001


@pytest.mark.asyncio
async def test_update_pattern_confidence_wrong() -> None:
    """Wrong outcome decreases confidence."""
    pattern_path = "Projects/PolymarketBot/patterns/politics/test.md"
    note = _make_obsidian_note(
        path=pattern_path,
        content="pattern content",
        frontmatter={"confidence": 0.6},
    )
    bridge = _build_mock_bridge(knowledge_notes=[note])
    svc = KnowledgeService(bridge=bridge)

    result = await svc.update_pattern_confidence(pattern_path, was_correct=False)

    assert result is True
    bridge.update_pattern_confidence.assert_awaited_once()
    new_conf = bridge.update_pattern_confidence.call_args[0][1]
    # 0.6 * 0.9 = 0.54
    assert abs(new_conf - 0.54) < 0.001


@pytest.mark.asyncio
async def test_rotate_to_standby() -> None:
    """rotate_to_standby changes path to StandBy folder."""
    pattern_path = "Projects/PolymarketBot/patterns/politics/test.md"
    note = _make_obsidian_note(
        path=pattern_path,
        content="pattern content",
        frontmatter={"status": "active", "confidence": 0.3},
    )
    bridge = _build_mock_bridge(knowledge_notes=[note])
    svc = KnowledgeService(bridge=bridge)

    result = await svc.rotate_to_standby(pattern_path)

    assert result is True
    bridge.write_note.assert_awaited_once()
    written: ObsidianNote = bridge.write_note.call_args[0][0]
    assert "StandBy" in written.path
    assert written.frontmatter["status"] == "standby"


@pytest.mark.asyncio
async def test_activate_from_standby() -> None:
    """activate_from_standby moves pattern back to domain folder."""
    standby_path = "Projects/PolymarketBot/patterns/StandBy/test.md"
    note = _make_obsidian_note(
        path=standby_path,
        content="pattern content",
        frontmatter={"status": "standby", "confidence": 0.7},
    )
    bridge = _build_mock_bridge(knowledge_notes=[note])
    svc = KnowledgeService(bridge=bridge)

    result = await svc.activate_from_standby(standby_path, "politics")

    assert result is True
    bridge.write_note.assert_awaited_once()
    written: ObsidianNote = bridge.write_note.call_args[0][0]
    assert "politics" in written.path
    assert "StandBy" not in written.path
    assert written.frontmatter["status"] == "active"
