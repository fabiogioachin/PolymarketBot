"""Knowledge service: orchestrates pattern management and KG operations."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.knowledge.obsidian_bridge import ObsidianBridge, ObsidianNote, PatternNote
from app.models.knowledge import (
    KnowledgeContext,
    Pattern,
    PatternMatch,
    PatternStatus,
)
from app.models.manifold import CrossPlatformSignal

logger = get_logger(__name__)


class KnowledgeService:
    """Orchestrates knowledge graph operations for the intelligence pipeline."""

    def __init__(self, bridge: ObsidianBridge | None = None) -> None:
        self._bridge = bridge or ObsidianBridge()
        self._patterns_path = app_config.intelligence.obsidian.patterns_path
        self._pattern_cache: dict[str, list[Pattern]] = {}

    async def read_patterns(self, domain: str) -> list[Pattern]:
        """Read active patterns for a domain from the KG."""
        notes = await self._bridge.read_patterns(domain)
        patterns = [self._note_to_pattern(note, domain) for note in notes]

        # Filter to active only
        active = [p for p in patterns if p.status == PatternStatus.ACTIVE]
        self._pattern_cache[domain] = active

        logger.info(
            "patterns_loaded", domain=domain, total=len(patterns), active=len(active)
        )
        return active

    async def read_domain_knowledge(self, domain: str) -> list[str]:
        """Read domain knowledge notes (concepts, background info)."""
        folder = f"Knowledge/{domain}"
        paths = await self._bridge.list_notes(folder)

        notes: list[str] = []
        for path in paths[:20]:  # cap reads
            note = await self._bridge.read_note(path)
            if note and note.content:
                notes.append(note.content[:1000])  # truncate for context

        return notes

    async def match_patterns(
        self,
        domain: str,
        event_text: str,
        *,
        keywords: list[str] | None = None,
    ) -> list[PatternMatch]:
        """Match current events/text against domain patterns."""
        patterns = self._pattern_cache.get(domain)
        if patterns is None:
            patterns = await self.read_patterns(domain)

        matches: list[PatternMatch] = []
        event_lower = event_text.lower()
        event_words = set(event_lower.split())

        for pattern in patterns:
            # Keyword matching
            pattern_words = set(pattern.description.lower().split())
            if pattern.trigger_condition:
                pattern_words.update(pattern.trigger_condition.lower().split())

            # User-provided keywords boost
            kw_set = {k.lower() for k in (keywords or [])}

            overlap = event_words & pattern_words
            kw_matches = kw_set & pattern_words if kw_set else set()

            if not overlap and not kw_matches:
                continue

            # Score based on overlap + confidence
            base_score = len(overlap) / max(len(pattern_words), 1)
            kw_boost = len(kw_matches) * 0.1 if kw_matches else 0
            match_score = min(1.0, (base_score + kw_boost) * pattern.confidence)

            if match_score < 0.1:
                continue

            matches.append(
                PatternMatch(
                    pattern=pattern,
                    match_score=round(match_score, 3),
                    matched_keywords=sorted(overlap | kw_matches),
                    detail=(
                        f"Matched {len(overlap)} words, confidence={pattern.confidence}"
                    ),
                )
            )

        # Sort by score
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches

    async def build_knowledge_context(
        self,
        domain: str,
        event_text: str = "",
        *,
        keywords: list[str] | None = None,
    ) -> KnowledgeContext:
        """Build complete knowledge context for market assessment."""
        patterns = await self.match_patterns(
            domain, event_text, keywords=keywords
        )
        domain_notes = await self.read_domain_knowledge(domain)

        # Composite signal from matched patterns
        signal = 0.0
        confidence = 0.0
        if patterns:
            # Weighted average of pattern signals
            total_weight = sum(m.match_score for m in patterns)
            if total_weight > 0:
                signal = sum(
                    m.match_score * m.pattern.confidence for m in patterns
                ) / total_weight
                confidence = min(1.0, total_weight / 3)  # normalize

        return KnowledgeContext(
            domain=domain,
            patterns=patterns,
            domain_notes=domain_notes,
            composite_signal=round(signal, 4),
            confidence=round(confidence, 4),
        )

    async def record_divergence(
        self,
        signal: CrossPlatformSignal,
        poly_question: str,
        manifold_url: str,
        *,
        min_divergence: float = 0.10,
    ) -> bool:
        """Record a significant cross-platform divergence to the Obsidian vault.

        Only writes if the absolute divergence exceeds min_divergence.
        """
        if abs(signal.divergence) < min_divergence:
            return False

        return await self._bridge.write_divergence_event(
            polymarket_id=signal.polymarket_id,
            manifold_id=signal.manifold_id,
            poly_price=signal.poly_price,
            manifold_price=signal.manifold_price,
            divergence=signal.divergence,
            poly_question=poly_question,
            manifold_url=manifold_url,
        )

    async def write_event(
        self,
        domain: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> bool:
        """Write a new event/discovery to the KG."""
        now = datetime.now(tz=UTC)
        safe_title = title.replace("/", "-").replace("\\", "-")[:80]
        path = f"Projects/PolymarketBot/Events/{domain}/{safe_title}.md"

        note = ObsidianNote(
            path=path,
            content=content,
            frontmatter={
                "type": "event",
                "domain": domain,
                "created": now.isoformat(),
                "tags": tags or [],
            },
            tags=tags or [],
        )
        return await self._bridge.write_note(note)

    async def update_pattern_confidence(
        self, pattern_path: str, *, was_correct: bool
    ) -> bool:
        """Update a pattern's confidence based on outcome."""
        note = await self._bridge.read_note(pattern_path)
        if note is None:
            return False

        current = float(note.frontmatter.get("confidence", 0.5))
        # Bayesian update: nudge toward 1 if correct, toward 0 if wrong
        new_conf = current + (1 - current) * 0.1 if was_correct else current * 0.9

        return await self._bridge.update_pattern_confidence(pattern_path, new_conf)

    async def rotate_to_standby(self, pattern_path: str) -> bool:
        """Move a pattern to StandBy (low confidence or inactive)."""
        note = await self._bridge.read_note(pattern_path)
        if note is None:
            return False
        note.frontmatter["status"] = "standby"
        # Move to StandBy folder
        filename = pattern_path.split("/")[-1]
        standby_path = f"{self._patterns_path}/StandBy/{filename}"
        note.path = standby_path
        return await self._bridge.write_note(note)

    async def activate_from_standby(self, pattern_path: str, domain: str) -> bool:
        """Reactivate a pattern from StandBy."""
        note = await self._bridge.read_note(pattern_path)
        if note is None:
            return False
        note.frontmatter["status"] = "active"
        filename = pattern_path.split("/")[-1]
        active_path = f"{self._patterns_path}/{domain}/{filename}"
        note.path = active_path
        return await self._bridge.write_note(note)

    @staticmethod
    def _note_to_pattern(note: PatternNote, domain: str) -> Pattern:
        """Convert an ObsidianBridge PatternNote to a Knowledge Pattern."""
        return Pattern(
            id=note.path,
            name=note.name,
            domain=note.domain or domain,
            pattern_type=note.pattern_type,
            confidence=note.confidence,
            status=PatternStatus.ACTIVE,  # read from active folder
            description=note.description,
            expected_outcome=note.expected_outcome,
            last_triggered=note.last_triggered,
            tags=note.tags,
        )
