"""Manifold Markets cross-platform matching and signal generation service.

Matches Polymarket markets to Manifold equivalents using TF-IDF cosine
similarity, then produces cross-platform divergence signals for the
Value Assessment Engine.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.clients.manifold_client import ManifoldClient
from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.manifold import CrossPlatformSignal, MarketMatch
from app.models.market import Market

logger = get_logger(__name__)


class ManifoldService:
    """Matches Polymarket markets to Manifold equivalents and generates
    cross-platform divergence signals."""

    def __init__(self, client: ManifoldClient) -> None:
        self._client = client
        self._cfg = app_config.intelligence.manifold
        self._match_cache: dict[str, MarketMatch | None] = {}  # poly_id -> match
        self._cache_time: dict[str, float] = {}  # poly_id -> timestamp
        self._cache_ttl = 3600.0  # 1 hour

    # ── Market matching ──────────────────────────────────────────────

    async def match_market(self, poly_market: Market) -> MarketMatch | None:
        """Find the best Manifold equivalent for a Polymarket market.

        Uses cached results when available and not expired. Scores candidates
        with TF-IDF cosine similarity against the Polymarket question.
        """
        # Check cache
        if poly_market.id in self._match_cache:
            cached_at = self._cache_time.get(poly_market.id, 0.0)
            if time.monotonic() - cached_at < self._cache_ttl:
                return self._match_cache[poly_market.id]

        # Build search query: first 80 chars, strip punctuation
        query = re.sub(r"[^\w\s]", "", poly_market.question[:80]).strip()
        if not query:
            self._match_cache[poly_market.id] = None
            self._cache_time[poly_market.id] = time.monotonic()
            return None

        candidates = await self._client.search_markets(query, limit=10)

        # Filter: skip resolved, low-liquidity, low-bettor markets
        candidates = [
            m
            for m in candidates
            if not m.is_resolved
            and m.total_liquidity >= self._cfg.min_manifold_volume
            and m.unique_bettor_count >= self._cfg.min_unique_bettors
        ]

        if not candidates:
            self._match_cache[poly_market.id] = None
            self._cache_time[poly_market.id] = time.monotonic()
            return None

        # TF-IDF cosine similarity scoring
        texts = [poly_market.question] + [m.question for m in candidates]
        tfidf = TfidfVectorizer(stop_words="english").fit_transform(texts)
        scores = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()

        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score >= self._cfg.match_confidence_threshold:
            best = candidates[best_idx]
            match = MarketMatch(
                polymarket_id=poly_market.id,
                manifold_id=best.id,
                manifold_url=best.url,
                polymarket_question=poly_market.question,
                manifold_question=best.question,
                similarity_score=best_score,
                match_method="tfidf",
                matched_at=datetime.now(UTC),
            )
            self._match_cache[poly_market.id] = match
            self._cache_time[poly_market.id] = time.monotonic()
            return match

        self._match_cache[poly_market.id] = None
        self._cache_time[poly_market.id] = time.monotonic()
        return None

    async def match_batch(self, markets: list[Market]) -> dict[str, MarketMatch]:
        """Match a list of Polymarket markets to Manifold equivalents.

        Processes sequentially to respect rate limits. Returns a dict keyed
        by Polymarket market ID for non-None matches only.
        """
        result: dict[str, MarketMatch] = {}
        for market in markets:
            match = await self.match_market(market)
            if match is not None:
                result[market.id] = match

        logger.info(
            "manifold_batch_matched",
            total=len(markets),
            matched=len(result),
        )
        return result

    # ── Cross-platform signals ───────────────────────────────────────

    async def get_cross_platform_signal(
        self, poly_market: Market, match: MarketMatch
    ) -> CrossPlatformSignal | None:
        """Generate a cross-platform divergence signal from a matched pair.

        Fetches current Manifold data and computes the divergence between
        Manifold probability and Polymarket YES price.
        """
        manifold = await self._client.get_market(match.manifold_id)

        poly_price = self._get_yes_price(poly_market)
        divergence = manifold.probability - poly_price
        signal_value = manifold.probability

        # Confidence: match quality x market quality
        liquidity_factor = min(1.0, manifold.total_liquidity / 10000)
        bettor_factor = min(1.0, manifold.unique_bettor_count / 100)
        quality = (liquidity_factor + bettor_factor) / 2
        confidence = match.similarity_score * quality

        return CrossPlatformSignal(
            polymarket_id=match.polymarket_id,
            manifold_id=match.manifold_id,
            poly_price=poly_price,
            manifold_price=manifold.probability,
            divergence=divergence,
            manifold_volume=manifold.volume,
            manifold_liquidity=manifold.total_liquidity,
            manifold_unique_bettors=manifold.unique_bettor_count,
            confidence=confidence,
            signal_value=signal_value,
            timestamp=datetime.now(UTC),
        )

    async def get_signals_batch(self, markets: list[Market]) -> dict[str, CrossPlatformSignal]:
        """Match markets and generate cross-platform signals for all matches.

        Returns a dict keyed by Polymarket market ID.
        """
        matches = await self.match_batch(markets)
        signals: dict[str, CrossPlatformSignal] = {}

        for poly_id, match in matches.items():
            # Find the original market for this match
            market = next((m for m in markets if m.id == poly_id), None)
            if market is None:
                continue
            signal = await self.get_cross_platform_signal(market, match)
            if signal is not None:
                signals[poly_id] = signal

        return signals

    # ── Cache management ─────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear all cached market matches."""
        self._match_cache.clear()
        self._cache_time.clear()

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _get_yes_price(market: Market) -> float:
        """Extract the YES outcome price from a Polymarket market."""
        for outcome in market.outcomes:
            if outcome.outcome.lower() == "yes":
                return outcome.price
        return 0.5
