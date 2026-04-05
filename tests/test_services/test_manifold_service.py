"""Tests for ManifoldService: market matching and cross-platform signals."""

from __future__ import annotations

import httpx
import respx

from app.clients.manifold_client import ManifoldClient
from app.models.market import Market, Outcome
from app.services.manifold_service import ManifoldService

SEARCH_URL = "https://api.manifold.markets/v0/search-markets"
MARKET_URL = "https://api.manifold.markets/v0/market/"


def _make_service(threshold: float = 0.6) -> ManifoldService:
    """Create a ManifoldService with a fast-retry client for testing."""
    client = ManifoldClient(rate_limit=5, max_retries=1, backoff=0.01)
    svc = ManifoldService(client)
    svc._cfg.match_confidence_threshold = threshold
    svc._cfg.min_manifold_volume = 100.0
    svc._cfg.min_unique_bettors = 5
    return svc


def _poly_market(
    market_id: str = "poly-1",
    question: str = "Will Bitcoin exceed $100,000 by end of 2026?",
    yes_price: float = 0.65,
) -> Market:
    return Market(
        id=market_id,
        question=question,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=1 - yes_price),
        ],
    )


def _manifold_json(
    mid: str = "mf-1",
    question: str = "Will Bitcoin exceed $100,000 by end of 2026?",
    probability: float = 0.70,
    total_liquidity: float = 5000.0,
    unique_bettor_count: int = 50,
    is_resolved: bool = False,
) -> dict:
    return {
        "id": mid,
        "question": question,
        "url": f"https://manifold.markets/{mid}",
        "probability": probability,
        "outcomeType": "BINARY",
        "mechanism": "cpmm-1",
        "volume": 12000.0,
        "volume24Hours": 300.0,
        "totalLiquidity": total_liquidity,
        "uniqueBettorCount": unique_bettor_count,
        "isResolved": is_resolved,
        "createdTime": 1700000000,
        "lastUpdatedTime": 1700100000,
        "creatorId": "creator-1",
        "groupSlugs": ["crypto"],
        "textDescription": "Bitcoin price prediction",
    }


# ── match_market ─────────────────────────────────────────────────────


class TestMatchMarket:
    @respx.mock
    async def test_successful_match(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        manifold_data = _manifold_json()

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))

        match = await svc.match_market(poly)

        assert match is not None
        assert match.polymarket_id == "poly-1"
        assert match.manifold_id == "mf-1"
        assert match.similarity_score > 0.0
        assert match.match_method == "tfidf"
        assert match.matched_at is not None

    @respx.mock
    async def test_no_candidates_returns_none(self) -> None:
        svc = _make_service()
        poly = _poly_market()

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[]))

        match = await svc.match_market(poly)
        assert match is None

    @respx.mock
    async def test_filters_resolved_markets(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        resolved = _manifold_json(is_resolved=True)

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[resolved]))

        match = await svc.match_market(poly)
        assert match is None

    @respx.mock
    async def test_filters_low_liquidity(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        low_liq = _manifold_json(total_liquidity=10.0)

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[low_liq]))

        match = await svc.match_market(poly)
        assert match is None

    @respx.mock
    async def test_filters_low_bettors(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        low_bettors = _manifold_json(unique_bettor_count=2)

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[low_bettors]))

        match = await svc.match_market(poly)
        assert match is None

    @respx.mock
    async def test_low_similarity_returns_none(self) -> None:
        svc = _make_service(threshold=0.99)
        poly = _poly_market(question="Will it rain in Rome tomorrow?")
        unrelated = _manifold_json(question="When will SpaceX land on Mars?")

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[unrelated]))

        match = await svc.match_market(poly)
        assert match is None

    @respx.mock
    async def test_cache_hit(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        manifold_data = _manifold_json()

        route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))

        match1 = await svc.match_market(poly)
        match2 = await svc.match_market(poly)

        assert match1 is not None
        assert match2 is not None
        assert match1.manifold_id == match2.manifold_id
        # Second call should use cache — only one HTTP call
        assert route.call_count == 1

    @respx.mock
    async def test_cache_expiry(self) -> None:
        svc = _make_service()
        svc._cache_ttl = 0.0  # expire immediately
        poly = _poly_market()
        manifold_data = _manifold_json()

        route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))

        await svc.match_market(poly)
        await svc.match_market(poly)

        # Both calls should hit the API since cache expires immediately
        assert route.call_count == 2

    @respx.mock
    async def test_picks_best_of_multiple_candidates(self) -> None:
        svc = _make_service()
        poly = _poly_market(question="Will Bitcoin exceed $100,000 by end of 2026?")
        good = _manifold_json(
            mid="mf-good",
            question="Will Bitcoin exceed $100,000 by end of 2026?",
        )
        bad = _manifold_json(
            mid="mf-bad",
            question="Will Ethereum reach $10,000 by 2027?",
        )

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[bad, good]))

        match = await svc.match_market(poly)
        assert match is not None
        assert match.manifold_id == "mf-good"


# ── match_batch ──────────────────────────────────────────────────────


class TestMatchBatch:
    @respx.mock
    async def test_batch_returns_matched_only(self) -> None:
        svc = _make_service()
        poly1 = _poly_market(market_id="p1", question="Will Bitcoin hit 100k?")
        poly2 = _poly_market(
            market_id="p2",
            question="Will the Fed cut rates in June?",
        )

        m1 = _manifold_json(mid="mf-1", question="Will Bitcoin hit 100k?")

        # First search returns a match, second returns empty
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.Response(200, json=[m1]),
            httpx.Response(200, json=[]),
        ]

        result = await svc.match_batch([poly1, poly2])

        assert "p1" in result
        assert "p2" not in result
        assert len(result) == 1


# ── get_cross_platform_signal ────────────────────────────────────────


class TestCrossPlatformSignal:
    @respx.mock
    async def test_signal_computation(self) -> None:
        svc = _make_service()
        poly = _poly_market(yes_price=0.65)
        manifold_data = _manifold_json(
            probability=0.72,
            total_liquidity=5000.0,
            unique_bettor_count=50,
        )

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))
        respx.get(url__startswith=MARKET_URL).mock(
            return_value=httpx.Response(200, json=manifold_data)
        )

        match = await svc.match_market(poly)
        assert match is not None

        signal = await svc.get_cross_platform_signal(poly, match)
        assert signal is not None
        assert signal.poly_price == 0.65
        assert signal.manifold_price == 0.72
        assert abs(signal.divergence - 0.07) < 1e-9
        assert signal.signal_value == 0.72
        assert signal.confidence > 0.0
        assert signal.timestamp is not None

    @respx.mock
    async def test_confidence_scales_with_quality(self) -> None:
        """Higher liquidity/bettors should produce higher confidence."""
        svc = _make_service()
        poly = _poly_market()

        low_q = _manifold_json(total_liquidity=500.0, unique_bettor_count=10)
        high_q = _manifold_json(
            mid="mf-hq",
            total_liquidity=20000.0,
            unique_bettor_count=200,
        )

        # Match with low quality market
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[low_q]))
        respx.get(url__startswith=MARKET_URL).mock(return_value=httpx.Response(200, json=low_q))

        match_low = await svc.match_market(poly)
        assert match_low is not None
        signal_low = await svc.get_cross_platform_signal(poly, match_low)

        # Reset cache and remock for high quality
        svc.clear_cache()
        respx.reset()

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[high_q]))
        respx.get(url__startswith=MARKET_URL).mock(return_value=httpx.Response(200, json=high_q))

        match_high = await svc.match_market(poly)
        assert match_high is not None
        signal_high = await svc.get_cross_platform_signal(poly, match_high)

        assert signal_low is not None
        assert signal_high is not None
        assert signal_high.confidence > signal_low.confidence


# ── get_signals_batch ────────────────────────────────────────────────


class TestSignalsBatch:
    @respx.mock
    async def test_end_to_end_batch(self) -> None:
        svc = _make_service()
        poly = _poly_market(yes_price=0.60)
        manifold_data = _manifold_json(probability=0.68)

        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))
        respx.get(url__startswith=MARKET_URL).mock(
            return_value=httpx.Response(200, json=manifold_data)
        )

        signals = await svc.get_signals_batch([poly])

        assert "poly-1" in signals
        sig = signals["poly-1"]
        assert sig.poly_price == 0.60
        assert sig.manifold_price == 0.68
        assert abs(sig.divergence - 0.08) < 1e-9


# ── clear_cache ──────────────────────────────────────────────────────


class TestClearCache:
    @respx.mock
    async def test_clear_cache_forces_refetch(self) -> None:
        svc = _make_service()
        poly = _poly_market()
        manifold_data = _manifold_json()

        route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=[manifold_data]))

        await svc.match_market(poly)
        assert route.call_count == 1

        svc.clear_cache()
        await svc.match_market(poly)
        assert route.call_count == 2


# ── _get_yes_price ───────────────────────────────────────────────────


class TestGetYesPrice:
    def test_extracts_yes_price(self) -> None:
        market = _poly_market(yes_price=0.73)
        assert ManifoldService._get_yes_price(market) == 0.73

    def test_returns_default_when_no_yes_outcome(self) -> None:
        market = Market(
            id="no-yes",
            question="Test",
            outcomes=[Outcome(token_id="t1", outcome="No", price=0.4)],
        )
        assert ManifoldService._get_yes_price(market) == 0.5

    def test_case_insensitive(self) -> None:
        market = Market(
            id="case",
            question="Test",
            outcomes=[
                Outcome(token_id="t1", outcome="YES", price=0.88),
            ],
        )
        assert ManifoldService._get_yes_price(market) == 0.88
