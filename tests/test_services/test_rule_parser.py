"""Tests for the resolution rule parser."""

from datetime import UTC, datetime

import pytest

from app.models.market import Market, ResolutionRules
from app.services.rule_parser import RuleParser, RuleRiskLevel


def _make_market(
    *,
    description: str = "",
    raw_text: str = "",
    source: str = "",
    conditions: list[str] | None = None,
    deadline: datetime | None = None,
    end_date: datetime | None = None,
) -> Market:
    """Helper to build a Market with specific resolution rules."""
    return Market(
        id="test-market-1",
        question="Will X happen?",
        description=description,
        resolution_rules=ResolutionRules(
            source=source,
            conditions=conditions or [],
            deadline=deadline,
            raw_text=raw_text,
        ),
        end_date=end_date,
    )


@pytest.fixture
def parser() -> RuleParser:
    return RuleParser()


class TestRuleRiskClassification:
    def test_clear_rules(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="This market resolves based on Associated Press reporting.",
            source="Associated Press",
            conditions=["This market resolves Yes if AP confirms the event."],
        )
        analysis = parser.analyze(market)
        assert analysis.risk_level == RuleRiskLevel.CLEAR

    def test_ambiguous_rules(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text=(
                "This market resolves at the discretion of the resolution committee. "
                "Data from Reuters."
            ),
            conditions=["Resolves based on committee decision."],
        )
        analysis = parser.analyze(market)
        assert analysis.risk_level == RuleRiskLevel.AMBIGUOUS

    def test_high_risk_rules(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text=(
                "Resolution may be determined approximately based on "
                "whatever the community decides. It could be anything."
            ),
        )
        analysis = parser.analyze(market)
        assert analysis.risk_level == RuleRiskLevel.HIGH_RISK


class TestSourceExtraction:
    def test_extract_source_ap(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="This market resolves according to Associated Press reporting.",
        )
        analysis = parser.analyze(market)
        assert analysis.resolution_source == "Associated Press"

    def test_extract_source_from_existing(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="Some text without clear source.",
            source="Official Government Data",
        )
        analysis = parser.analyze(market)
        assert analysis.resolution_source == "Official Government Data"

    def test_extract_source_according_to(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="Resolution will be determined according to CoinGecko data.",
        )
        analysis = parser.analyze(market)
        assert analysis.resolution_source == "CoinGecko data"

    def test_extract_source_trusted_keyword(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="The federal reserve will publish the data used for resolution.",
        )
        analysis = parser.analyze(market)
        assert analysis.resolution_source == "Federal Reserve"


class TestEdgeCaseDetection:
    def test_detect_timezone_edge_case(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="This market resolves by January 15, 2026. No timezone specified.",
        )
        analysis = parser.analyze(market)
        assert any("timezone" in ec.lower() for ec in analysis.edge_cases)

    def test_detect_multiple_timezones(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text=(
                "The event must occur before 5pm EST on Friday. "
                "Data will be checked at 9am PST on Monday."
            ),
        )
        analysis = parser.analyze(market)
        assert any("multiple timezones" in ec.lower() for ec in analysis.edge_cases)

    def test_detect_conditional_resolution(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="If the candidate wins the primary, then the market resolves Yes.",
        )
        analysis = parser.analyze(market)
        assert any("conditional" in ec.lower() for ec in analysis.edge_cases)

    def test_detect_official_without_named_source(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="Resolution based on official results from the relevant authority.",
        )
        analysis = parser.analyze(market)
        assert any("official" in ec.lower() for ec in analysis.edge_cases)


class TestAmbiguityDetection:
    def test_detect_ambiguity_markers(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text=(
                "The outcome may be subject to change. "
                "Resolution is approximately based on available data. "
                "Reuters will be consulted."
            ),
        )
        analysis = parser.analyze(market)
        assert len(analysis.ambiguities) >= 2
        assert any("may be" in a for a in analysis.ambiguities)
        assert any("subject to" in a for a in analysis.ambiguities)

    def test_no_conditions_is_ambiguous(self, parser: RuleParser) -> None:
        market = _make_market(
            raw_text="Some generic description with no clear rules at all.",
            source="Reuters",
        )
        analysis = parser.analyze(market)
        assert analysis.risk_level in (RuleRiskLevel.AMBIGUOUS, RuleRiskLevel.HIGH_RISK)


class TestFullAnalysis:
    def test_analyze_returns_full_analysis(self, parser: RuleParser) -> None:
        end = datetime(2026, 6, 1, tzinfo=UTC)
        market = _make_market(
            description="Backup description text.",
            raw_text=(
                "This market resolves Yes if the Associated Press confirms "
                "the event by June 1, 2026 EST. Resolution may be delayed "
                "if results are contested."
            ),
            conditions=["Resolves Yes if AP confirms the event."],
            end_date=end,
        )
        analysis = parser.analyze(market)

        assert analysis.market_id == "test-market-1"
        assert analysis.resolution_source == "Associated Press"
        assert len(analysis.conditions) >= 1
        assert analysis.deadline == end
        assert analysis.raw_text != ""
        # Should detect "may be" ambiguity
        assert len(analysis.ambiguities) >= 1

    def test_falls_back_to_description(self, parser: RuleParser) -> None:
        market = _make_market(
            description="According to Reuters, this market resolves on outcome.",
            raw_text="",
        )
        analysis = parser.analyze(market)
        assert analysis.resolution_source == "Reuters"
        assert analysis.raw_text == "According to Reuters, this market resolves on outcome."
