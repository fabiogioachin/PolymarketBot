"""Tests for pattern templates and seed data."""

from app.knowledge.pattern_templates import (
    PatternTemplate,
    get_seed_patterns,
    render_pattern_markdown,
)


class TestGetSeedPatterns:
    def test_returns_at_least_25_patterns(self) -> None:
        patterns = get_seed_patterns()
        assert len(patterns) >= 25

    def test_all_patterns_have_required_fields(self) -> None:
        for p in get_seed_patterns():
            assert p.name, f"Pattern missing name: {p}"
            assert p.domain, f"Pattern missing domain: {p.name}"
            assert p.pattern_type, f"Pattern missing pattern_type: {p.name}"
            assert p.description, f"Pattern missing description: {p.name}"

    def test_all_domains_covered(self) -> None:
        domains = {p.domain for p in get_seed_patterns()}
        expected = {"geopolitics", "politics", "economics", "crypto", "sports"}
        assert expected.issubset(domains)

    def test_each_domain_has_at_least_4_patterns(self) -> None:
        by_domain: dict[str, int] = {}
        for p in get_seed_patterns():
            by_domain[p.domain] = by_domain.get(p.domain, 0) + 1
        for domain, count in by_domain.items():
            assert count >= 4, f"Domain {domain} has only {count} patterns"

    def test_all_pattern_types_present(self) -> None:
        types = {p.pattern_type for p in get_seed_patterns()}
        expected = {"recurring", "seasonal", "causal", "correlation"}
        assert expected.issubset(types)

    def test_confidence_values_valid(self) -> None:
        for p in get_seed_patterns():
            assert 0 <= p.confidence <= 1, f"{p.name}: confidence {p.confidence}"

    def test_tags_non_empty(self) -> None:
        for p in get_seed_patterns():
            assert len(p.tags) > 0, f"{p.name} has no tags"

    def test_historical_accuracy_valid(self) -> None:
        for p in get_seed_patterns():
            assert 0 <= p.historical_accuracy <= 1, f"{p.name}: accuracy {p.historical_accuracy}"


class TestRenderPatternMarkdown:
    def _get_first(self) -> PatternTemplate:
        return get_seed_patterns()[0]

    def test_starts_with_yaml_frontmatter(self) -> None:
        md = render_pattern_markdown(self._get_first())
        assert md.startswith("---\n")
        assert "\n---\n" in md[4:]  # closing delimiter

    def test_frontmatter_contains_required_fields(self) -> None:
        md = render_pattern_markdown(self._get_first())
        assert "type:" in md
        assert "domain:" in md
        assert "confidence:" in md
        assert "status:" in md

    def test_body_contains_description_section(self) -> None:
        md = render_pattern_markdown(self._get_first())
        assert "## Description" in md

    def test_body_contains_trigger_condition(self) -> None:
        md = render_pattern_markdown(self._get_first())
        assert "## Trigger Condition" in md

    def test_body_contains_historical_performance(self) -> None:
        md = render_pattern_markdown(self._get_first())
        assert "## Historical Performance" in md

    def test_renders_all_patterns_without_error(self) -> None:
        for p in get_seed_patterns():
            md = render_pattern_markdown(p)
            assert len(md) > 100, f"Rendered markdown too short for {p.name}"
