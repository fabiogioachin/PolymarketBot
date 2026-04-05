"""Sentiment strategy — trades on GDELT tone/Goldstein signals."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)


class SentimentStrategy:
    """Trades on sentiment signals derived from GDELT tone analysis.

    Uses knowledge.composite_signal as the aggregated sentiment proxy
    (positive = bullish sentiment, negative = bearish). A signal is only
    emitted when sentiment direction matches the valuation edge direction
    and the sentiment shift is strong enough.
    """

    TONE_SHIFT_THRESHOLD: float = 1.5   # minimum |composite_signal| to act on
    MIN_VOLUME_RATIO: float = 1.5        # placeholder — can be enriched when volume data flows in

    def __init__(self) -> None:
        # Baseline tone per domain — updated by upstream intelligence layer
        self._baselines: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "sentiment"

    @property
    def domain_filter(self) -> list[str]:
        return ["politics", "geopolitics", "economics"]

    def update_baseline(self, domain: str, baseline_tone: float) -> None:
        """Update the baseline tone for a domain."""
        self._baselines[domain] = baseline_tone
        logger.debug("sentiment: baseline updated", domain=domain, baseline=baseline_tone)

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Return a BUY/SELL signal when sentiment and valuation edge agree.

        The sentiment proxy is knowledge.composite_signal (range -1 to +1).
        The shift magnitude is compared to TONE_SHIFT_THRESHOLD; if the raw
        signal is too weak, no trade is emitted. Direction must match the
        valuation fee_adjusted_edge for a signal to be produced.
        """
        if not knowledge:
            logger.debug("sentiment: no knowledge context", market_id=market.id)
            return None

        sentiment = knowledge.composite_signal
        edge = valuation.fee_adjusted_edge

        # Normalise: composite_signal is -1..+1; threshold is in the same scale
        # (TONE_SHIFT_THRESHOLD is divided by its natural max of ~100 for raw GDELT tone,
        # but composite_signal is already normalised, so we scale the threshold accordingly)
        effective_threshold = self.TONE_SHIFT_THRESHOLD / 100.0

        if abs(sentiment) < effective_threshold:
            logger.debug(
                "sentiment: signal below threshold",
                market_id=market.id,
                sentiment=sentiment,
                threshold=effective_threshold,
            )
            return None

        signal_type = self._resolve_signal_type(sentiment, edge)
        if signal_type is None:
            logger.debug(
                "sentiment: sentiment and edge disagree — no trade",
                market_id=market.id,
                sentiment=sentiment,
                edge=edge,
            )
            return None

        # Confidence: how strong the sentiment shift is relative to threshold
        sentiment_strength = min(1.0, abs(sentiment) / max(effective_threshold, 1e-9))
        confidence = round(
            sentiment_strength * knowledge.confidence * 0.8,  # cap at 0.8 for sentiment-only
            4,
        )

        token_id = self._pick_token(market, signal_type)
        domain_tag = knowledge.domain or market.category.value

        # Adjust for baseline if available
        baseline = self._baselines.get(domain_tag)
        baseline_note = (
            f" Baseline tone for '{domain_tag}': {baseline:.3f}." if baseline is not None else ""
        )

        reasoning = (
            f"Sentiment composite signal {sentiment:+.3f} "
            f"({'bullish' if sentiment > 0 else 'bearish'}) "
            f"aligns with fee-adjusted edge {edge:+.3f}.{baseline_note}"
        )

        logger.info(
            "sentiment: signal generated",
            market_id=market.id,
            signal_type=signal_type,
            sentiment=sentiment,
            edge=edge,
            confidence=confidence,
        )

        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=token_id,
            signal_type=signal_type,
            confidence=confidence,
            market_price=valuation.market_price,
            edge_amount=edge,
            reasoning=reasoning,
            timestamp=datetime.now(UTC),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_signal_type(
        self,
        sentiment: float,
        edge: float,
    ) -> SignalType | None:
        """Emit only when sentiment and edge directions agree."""
        if sentiment > 0 and edge > 0:
            return SignalType.BUY
        if sentiment < 0 and edge < 0:
            return SignalType.SELL
        return None

    def _pick_token(self, market: Market, signal_type: SignalType) -> str:
        if signal_type == SignalType.BUY:
            return next(
                (o.token_id for o in market.outcomes if o.outcome.lower() == "yes"),
                market.outcomes[0].token_id if market.outcomes else "",
            )
        return next(
            (o.token_id for o in market.outcomes if o.outcome.lower() == "no"),
            market.outcomes[0].token_id if market.outcomes else "",
        )
