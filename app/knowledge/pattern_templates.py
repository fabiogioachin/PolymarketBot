"""Pattern templates and seed data for the Knowledge Graph."""

from dataclasses import dataclass, field


@dataclass
class PatternTemplate:
    """Template for generating Obsidian pattern notes."""

    name: str
    domain: str  # geopolitics, politics, economics, crypto, sports
    pattern_type: str  # recurring, seasonal, causal, correlation
    confidence: float = 0.5
    description: str = ""
    expected_outcome: str = ""
    trigger_condition: str = ""
    historical_accuracy: float = 0.0
    season: str = ""  # if seasonal: "Q1", "summer", etc.
    actors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def get_seed_patterns() -> list[PatternTemplate]:
    """Return 25+ seed patterns across all domains."""
    return [
        # --- GEOPOLITICS (6 patterns) ---
        PatternTemplate(
            name="US-China Trade Tension Escalation",
            domain="geopolitics",
            pattern_type="recurring",
            confidence=0.65,
            description=(
                "Trade tensions between US and China tend to escalate in cycles, especially"
                " during election years or after economic data releases."
            ),
            expected_outcome=(
                "Markets related to US-China relations, tariffs, and trade agreements"
                " see increased volatility."
            ),
            trigger_condition=(
                "GDELT: high volume of articles with actors USA+CHN and themes TRADE/TARIFF"
            ),
            historical_accuracy=0.62,
            actors=["USA", "CHN"],
            tags=["trade", "tariff", "sanctions", "geopolitics"],
        ),
        PatternTemplate(
            name="Middle East Conflict Escalation Cycle",
            domain="geopolitics",
            pattern_type="recurring",
            confidence=0.55,
            description=(
                "Middle East conflicts tend to escalate in predictable cycles:"
                " incident → diplomatic response → military response → ceasefire negotiation."
            ),
            expected_outcome=(
                "Markets on conflict resolution tend to initially drop (NO prices rise)"
                " then recover."
            ),
            trigger_condition=(
                "GDELT: Goldstein score < -5 for Middle East actors, volume spike > 3x"
            ),
            historical_accuracy=0.58,
            actors=["ISR", "IRN", "SAU", "PSE"],
            tags=["conflict", "military", "ceasefire", "middle_east"],
        ),
        PatternTemplate(
            name="Russia-Ukraine Negotiation Window",
            domain="geopolitics",
            pattern_type="causal",
            confidence=0.45,
            description=(
                "Diplomatic signals (high-level meetings, UN resolutions) precede"
                " potential negotiation windows."
            ),
            expected_outcome=(
                "Ceasefire/negotiation market prices tend to spike temporarily on"
                " diplomatic signals, then revert."
            ),
            trigger_condition=("GDELT: tone shift > +2 for RUS+UKR, diplomatic event type"),
            historical_accuracy=0.40,
            actors=["RUS", "UKR"],
            tags=["diplomacy", "ceasefire", "negotiation"],
        ),
        PatternTemplate(
            name="EU Regulatory Wave",
            domain="geopolitics",
            pattern_type="seasonal",
            confidence=0.60,
            description=(
                "EU tends to announce major regulatory packages in Q1 and Q3,"
                " affecting tech, finance, and environmental markets."
            ),
            expected_outcome=(
                "Markets on EU regulation tend to move toward YES in weeks before announcement."
            ),
            trigger_condition="Calendar: Q1/Q3 + EU commission agenda items",
            season="Q1,Q3",
            historical_accuracy=0.58,
            actors=["EU"],
            tags=["regulation", "EU", "tech", "finance"],
        ),
        PatternTemplate(
            name="NATO Summit Market Impact",
            domain="geopolitics",
            pattern_type="recurring",
            confidence=0.50,
            description=(
                "NATO summits produce market-moving announcements on defense spending,"
                " alliance expansion, and posture changes."
            ),
            expected_outcome=(
                "Defense and geopolitical alignment markets see resolution acceleration"
                " around summit dates."
            ),
            trigger_condition=("Calendar: NATO summit scheduled + GDELT volume on NATO themes"),
            actors=["NATO", "USA", "EU"],
            tags=["NATO", "defense", "alliance"],
        ),
        PatternTemplate(
            name="Sanctions Escalation Cascade",
            domain="geopolitics",
            pattern_type="causal",
            confidence=0.55,
            description=(
                "Sanctions from one country tend to trigger counter-sanctions and"
                " market adjustments within 1-2 weeks."
            ),
            expected_outcome=(
                "Markets on sanctioned entities/countries shift toward resolution within"
                " 2 weeks of initial sanction."
            ),
            trigger_condition=("GDELT: sanction-related articles > 2x baseline for target country"),
            historical_accuracy=0.52,
            tags=["sanctions", "trade", "economic_warfare"],
        ),
        # --- POLITICS (5 patterns) ---
        PatternTemplate(
            name="US Election Polling Momentum",
            domain="politics",
            pattern_type="recurring",
            confidence=0.60,
            description=(
                "Polling momentum (3+ consecutive polls showing movement) correlates with"
                " market price movement, but tends to overshoot."
            ),
            expected_outcome=(
                "Market prices follow polling trends with a lag, creating edge when polls"
                " shift before prices."
            ),
            trigger_condition=(
                "RSS: 3+ major polls showing >2% shift in same direction within 1 week"
            ),
            historical_accuracy=0.65,
            actors=["USA"],
            tags=["election", "polling", "momentum"],
        ),
        PatternTemplate(
            name="Congressional Vote Whip Count",
            domain="politics",
            pattern_type="causal",
            confidence=0.70,
            description=(
                "Whip count leaks and member statements 24-48h before votes are strong"
                " predictors of bill passage."
            ),
            expected_outcome=(
                "Markets on legislation passage converge rapidly in the 48h before scheduled votes."
            ),
            trigger_condition=("RSS: major news outlets reporting whip counts or member positions"),
            historical_accuracy=0.72,
            actors=["USA"],
            tags=["legislation", "congress", "vote"],
        ),
        PatternTemplate(
            name="Supreme Court Decision Leak Pattern",
            domain="politics",
            pattern_type="seasonal",
            confidence=0.55,
            description=(
                "Major SCOTUS decisions cluster in June-July. Draft opinions sometimes"
                " leak before official release."
            ),
            expected_outcome=(
                "Legal/constitutional markets resolve in clusters during June-July term end."
            ),
            trigger_condition="Calendar: June-July + SCOTUS oral argument schedule",
            season="June-July",
            historical_accuracy=0.60,
            actors=["USA"],
            tags=["SCOTUS", "legal", "court"],
        ),
        PatternTemplate(
            name="Resignation Removal Cascade",
            domain="politics",
            pattern_type="causal",
            confidence=0.50,
            description=(
                "One high-profile resignation/firing often precedes a cascade of similar"
                " events within the same administration."
            ),
            expected_outcome=(
                "Markets on 'Will X resign/be fired' see correlated movement "
                "after initial departure."
            ),
            trigger_condition=(
                "News: confirmed high-profile departure + GDELT volume spike "
                "on administration themes"
            ),
            historical_accuracy=0.48,
            tags=["resignation", "government", "personnel"],
        ),
        PatternTemplate(
            name="Primary Season Volatility",
            domain="politics",
            pattern_type="seasonal",
            confidence=0.55,
            description=(
                "Primary/caucus nights cause rapid market repricing, often with overnight gaps."
            ),
            expected_outcome=(
                "Nomination markets see 10-20% swings on primary results, creating"
                " entry/exit opportunities."
            ),
            trigger_condition="Calendar: primary/caucus schedule dates",
            season="Jan-June (election years)",
            historical_accuracy=0.60,
            tags=["primary", "election", "nomination"],
        ),
        # --- ECONOMICS (5 patterns) ---
        PatternTemplate(
            name="Fed Rate Decision Anticipation",
            domain="economics",
            pattern_type="recurring",
            confidence=0.75,
            description=(
                "Markets price in Fed decisions 2-3 weeks before FOMC meetings."
                " The actual decision rarely surprises."
            ),
            expected_outcome=(
                "Rate decision markets converge to outcome 1-2 weeks before meeting."
                " Edge exists in early positioning."
            ),
            trigger_condition="Calendar: FOMC meeting dates + CME FedWatch tool probabilities",
            historical_accuracy=0.80,
            actors=["FED", "USA"],
            tags=["federal_reserve", "interest_rate", "FOMC"],
        ),
        PatternTemplate(
            name="CPI Release Market Impact",
            domain="economics",
            pattern_type="seasonal",
            confidence=0.65,
            description=(
                "CPI releases (monthly, ~10th) cause rapid repricing of inflation and rate markets."
            ),
            expected_outcome=(
                "Inflation markets adjust within hours of CPI release. Pre-release positioning"
                " based on nowcasts has edge."
            ),
            trigger_condition="Calendar: BLS CPI release date + Cleveland Fed nowcast",
            season="monthly",
            historical_accuracy=0.68,
            actors=["USA"],
            tags=["CPI", "inflation", "BLS"],
        ),
        PatternTemplate(
            name="Jobs Report Surprise Pattern",
            domain="economics",
            pattern_type="recurring",
            confidence=0.55,
            description=(
                "NFP reports that deviate >50k from consensus create rapid repricing across"
                " employment and rate markets."
            ),
            expected_outcome=(
                "Employment markets see 5-15% moves on surprise reports."
                " Edge in fast reaction to deviation."
            ),
            trigger_condition="Calendar: first Friday of month + ADP estimate comparison",
            historical_accuracy=0.60,
            actors=["USA"],
            tags=["jobs", "NFP", "employment", "BLS"],
        ),
        PatternTemplate(
            name="Recession Indicator Convergence",
            domain="economics",
            pattern_type="causal",
            confidence=0.60,
            description=(
                "When 3+ recession indicators (yield curve, PMI, unemployment claims) align,"
                " recession markets move."
            ),
            expected_outcome=(
                "Recession probability markets see sustained drift toward YES "
                "when indicators converge."
            ),
            trigger_condition=(
                "Multiple: yield curve inversion + PMI < 50 + rising initial claims"
            ),
            historical_accuracy=0.62,
            tags=["recession", "indicators", "yield_curve"],
        ),
        PatternTemplate(
            name="Central Bank Contagion",
            domain="economics",
            pattern_type="correlation",
            confidence=0.50,
            description=(
                "Rate decisions by major central banks (ECB, BOJ, BOE) within 1-2 weeks"
                " of each other tend to cluster in direction."
            ),
            expected_outcome=(
                "Cross-market rate decision markets show correlated movement after"
                " first major bank acts."
            ),
            trigger_condition="Calendar: clustered central bank meeting dates",
            historical_accuracy=0.52,
            actors=["ECB", "BOJ", "BOE", "FED"],
            tags=["central_bank", "rates", "correlation"],
        ),
        # --- CRYPTO (4 patterns) ---
        PatternTemplate(
            name="Bitcoin Halving Cycle",
            domain="crypto",
            pattern_type="seasonal",
            confidence=0.65,
            description=(
                "Bitcoin price tends to rally 6-18 months after halving events."
                " Crypto markets on Polymarket correlate."
            ),
            expected_outcome=(
                "Crypto price target markets become more likely YES "
                "in the year following a halving."
            ),
            trigger_condition="Calendar: months since last halving event",
            season="12-18 months post-halving",
            historical_accuracy=0.67,
            tags=["bitcoin", "halving", "cycle"],
        ),
        PatternTemplate(
            name="ETF Approval Cascade",
            domain="crypto",
            pattern_type="causal",
            confidence=0.70,
            description=(
                "Approval of one crypto ETF (e.g., BTC spot) increases probability of"
                " subsequent ETF approvals (ETH, SOL)."
            ),
            expected_outcome=(
                "Markets on 'Will X crypto ETF be approved' shift toward YES "
                "after a precedent approval."
            ),
            trigger_condition=(
                "News: SEC approval of crypto ETF + institutional filings for new ETFs"
            ),
            historical_accuracy=0.72,
            actors=["SEC", "USA"],
            tags=["ETF", "SEC", "regulation", "institutional"],
        ),
        PatternTemplate(
            name="DeFi Exploit Contagion",
            domain="crypto",
            pattern_type="causal",
            confidence=0.55,
            description=(
                "Major DeFi exploits/hacks cause temporary selloffs and increased"
                " regulatory scrutiny markets."
            ),
            expected_outcome=(
                "Regulation markets shift toward YES; crypto price markets see temporary dip."
            ),
            trigger_condition="GDELT/RSS: reports of DeFi hack > $50M",
            historical_accuracy=0.50,
            tags=["DeFi", "hack", "exploit", "regulation"],
        ),
        PatternTemplate(
            name="Crypto Regulation Wave",
            domain="crypto",
            pattern_type="recurring",
            confidence=0.60,
            description=(
                "Regulatory actions tend to cluster: one agency action often triggers"
                " coordinated responses from others."
            ),
            expected_outcome=(
                "Markets on crypto regulation show correlated movement across jurisdictions."
            ),
            trigger_condition=(
                "News: SEC/CFTC enforcement action + congressional hearing scheduling"
            ),
            historical_accuracy=0.55,
            actors=["SEC", "CFTC", "EU"],
            tags=["regulation", "enforcement", "compliance"],
        ),
        # --- SPORTS (5 patterns) ---
        PatternTemplate(
            name="Injury Report Market Lag",
            domain="sports",
            pattern_type="recurring",
            confidence=0.60,
            description=(
                "Official injury reports often lag social media/insider reports by hours."
                " Market adjusts slowly."
            ),
            expected_outcome=(
                "Game outcome markets under-react to injury news "
                "for 2-6 hours after initial report."
            ),
            trigger_condition=(
                "RSS/social: injury report for key player + official report not yet released"
            ),
            historical_accuracy=0.58,
            tags=["injury", "NBA", "NFL", "player_status"],
        ),
        PatternTemplate(
            name="Home Court Field Advantage Overestimation",
            domain="sports",
            pattern_type="recurring",
            confidence=0.55,
            description=(
                "Markets tend to overestimate home advantage in major sports, "
                "especially in playoffs."
            ),
            expected_outcome=(
                "Home team markets are slightly overpriced on average; systematic edge"
                " in betting against home favorites."
            ),
            trigger_condition="Market: home team priced > 60% in non-rivalry game",
            historical_accuracy=0.54,
            tags=["home_advantage", "bias", "overpricing"],
        ),
        PatternTemplate(
            name="Championship Series Momentum Reversal",
            domain="sports",
            pattern_type="recurring",
            confidence=0.50,
            description=(
                "After a dominant win in a playoff series, the losing team often bounces"
                " back in the next game."
            ),
            expected_outcome=(
                "Series markets after blowout wins tend to overreact, "
                "creating edge on the losing team."
            ),
            trigger_condition="Score: margin of victory > 20 points in previous game",
            historical_accuracy=0.52,
            tags=["playoffs", "momentum", "series", "reversal"],
        ),
        PatternTemplate(
            name="Transfer Window Speculation",
            domain="sports",
            pattern_type="seasonal",
            confidence=0.45,
            description=(
                "Football transfer windows (Jan, June-Aug) create speculation markets"
                " that tend to resolve NO."
            ),
            expected_outcome=(
                "Transfer rumor markets are overpriced; most speculated transfers don't happen."
            ),
            trigger_condition=("Calendar: transfer window open + media speculation reports"),
            season="Jan, June-August",
            historical_accuracy=0.40,
            tags=["football", "transfer", "speculation"],
        ),
        PatternTemplate(
            name="Weather Impact on Outdoor Events",
            domain="sports",
            pattern_type="causal",
            confidence=0.50,
            description=(
                "Extreme weather forecasts for outdoor events affect scoring "
                "and game outcome probabilities."
            ),
            expected_outcome=(
                "Under/over markets and specific scoring markets shift with weather forecasts."
            ),
            trigger_condition="Weather: forecast for game location shows extreme conditions",
            historical_accuracy=0.48,
            tags=["weather", "outdoor", "scoring"],
        ),
        # --- CROSS-PLATFORM (3 patterns) ---
        PatternTemplate(
            name="Cross-Platform Divergence Signal",
            domain="cross_platform",
            pattern_type="correlation",
            confidence=0.55,
            description=(
                "When Manifold and Polymarket diverge by >15% on the same market,"
                " one platform is likely mispriced. Manifold's play-money crowd"
                " sometimes spots qualitative signals that real-money traders miss."
            ),
            expected_outcome=(
                "Divergence >15% signals a potential edge. Direction depends on which"
                " platform has better information for the specific domain."
            ),
            trigger_condition=(
                "Cross-platform analyzer: |divergence| > 0.15 with match confidence > 0.7"
            ),
            historical_accuracy=0.0,
            tags=["cross_platform", "manifold", "divergence", "arbitrage"],
        ),
        PatternTemplate(
            name="Manifold Calibration Advantage",
            domain="cross_platform",
            pattern_type="recurring",
            confidence=0.50,
            description=(
                "Manifold markets tend to be better calibrated at extreme probabilities"
                " (<0.2 or >0.8). Real-money markets sometimes overreact to news,"
                " while play-money crowds anchor more to base rates."
            ),
            expected_outcome=(
                "When Polymarket price is extreme (>0.85 or <0.15) and Manifold"
                " disagrees by >10%, Manifold's estimate may be more accurate."
            ),
            trigger_condition=(
                "Cross-platform: Polymarket extreme price + Manifold moderate price"
            ),
            historical_accuracy=0.0,
            tags=["cross_platform", "calibration", "extreme_probability"],
        ),
        PatternTemplate(
            name="Volume-Weighted Divergence",
            domain="cross_platform",
            pattern_type="causal",
            confidence=0.45,
            description=(
                "Divergence is more meaningful when both platforms have high volume"
                " and many unique bettors. Low-volume Manifold markets should be"
                " heavily discounted."
            ),
            expected_outcome=(
                "High-quality matches (both platforms >$10k volume) with divergence"
                " >10% have higher predictive value than low-quality matches."
            ),
            trigger_condition=(
                "Cross-platform: both markets volume > threshold + divergence > 0.10"
            ),
            historical_accuracy=0.0,
            tags=["cross_platform", "volume", "quality", "divergence"],
        ),
    ]


def render_pattern_markdown(template: PatternTemplate) -> str:
    """Render a PatternTemplate as Obsidian-compatible Markdown with YAML frontmatter."""
    actors_str = ", ".join(template.actors) if template.actors else ""
    tags_str = "\n".join(f"  - {t}" for t in template.tags) if template.tags else ""

    frontmatter = f"""---
type: {template.pattern_type}
domain: {template.domain}
confidence: {template.confidence}
last_triggered: null
season: "{template.season}"
actors: "{actors_str}"
trigger_condition: "{template.trigger_condition}"
expected_outcome: "{template.expected_outcome}"
historical_accuracy: {template.historical_accuracy}
status: active
tags:
{tags_str}
---"""

    body = f"""# {template.name}

## Description
{template.description}

## Expected Outcome
{template.expected_outcome}

## Trigger Condition
{template.trigger_condition}

## Historical Performance
- **Accuracy**: {template.historical_accuracy * 100:.0f}%
- **Confidence**: {template.confidence * 100:.0f}%
- **Times Triggered**: 0

## Notes
_Seed pattern — requires validation against live data._
"""

    return frontmatter + "\n\n" + body
