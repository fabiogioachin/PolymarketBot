"""Value Assessment Engine: the core of the system."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.market import Market, OrderBook, PriceHistory
from app.models.valuation import (
    EdgeSource,
    Recommendation,
    ValuationInput,
    ValuationResult,
)
from app.valuation.base_rate import BaseRateAnalyzer
from app.valuation.cross_market import CrossMarketAnalyzer
from app.valuation.crowd_calibration import CrowdCalibrationAnalyzer
from app.valuation.db import ResolutionDB
from app.valuation.microstructure import MicrostructureAnalysis, MicrostructureAnalyzer
from app.valuation.temporal import TemporalAnalyzer

logger = get_logger(__name__)


class ValueAssessmentEngine:
    """Core engine: assesses fair value of prediction markets."""

    def __init__(self, db: ResolutionDB) -> None:
        self._db = db
        self._base_rate = BaseRateAnalyzer(db)
        self._calibration = CrowdCalibrationAnalyzer(db)
        self._microstructure = MicrostructureAnalyzer()
        self._cross_market = CrossMarketAnalyzer()
        self._temporal = TemporalAnalyzer()
        self._weights = app_config.valuation.weights
        self._thresholds = app_config.valuation.thresholds

    async def assess(
        self,
        market: Market,
        *,
        universe: list[Market] | None = None,
        orderbook_data: OrderBook | None = None,
        price_history: PriceHistory | None = None,
        event_signal: float | None = None,
        pattern_kg_signal: float | None = None,
        rule_analysis_score: float | None = None,
        cross_platform_signal: float | None = None,
    ) -> ValuationResult:
        """Assess a single market's fair value.

        This is the core method. It:
        1. Gathers signals from all analyzers
        2. Computes weighted fair value
        3. Calculates edge and confidence
        4. Produces recommendation
        """
        # Get market price (YES outcome)
        market_price = self._get_market_price(market)

        # 1. Base rate prior
        base_rate = await self._base_rate.get_prior(market)

        # 2. Crowd calibration adjustment
        calibration_adj = await self._calibration.get_adjustment(market.category.value)

        # 3. Microstructure (if data provided)
        micro_score: float | None = None
        if orderbook_data is not None or price_history is not None:
            micro_score = self._analyze_microstructure(orderbook_data, price_history)

        # 4. Cross-market (if universe provided)
        cross_signal: float | None = None
        if universe:
            cross_analysis = self._cross_market.find_correlations(market, universe)
            cross_signal = cross_analysis.composite_signal

        # 5. Temporal factor
        temporal_factor = self._temporal.compute_temporal_factor(market)

        # Build input record
        inputs = ValuationInput(
            market_id=market.id,
            market_price=market_price,
            base_rate=base_rate,
            crowd_calibration_adjustment=calibration_adj,
            rule_analysis_score=rule_analysis_score,
            microstructure_score=micro_score,
            cross_market_signal=cross_signal,
            event_signal=event_signal,
            pattern_kg_signal=pattern_kg_signal,
            cross_platform_signal=cross_platform_signal,
            temporal_factor=temporal_factor,
        )

        # Compute fair value
        fair_value, edge_sources, confidence = self._compute_fair_value(inputs)

        # Apply temporal scaling to edge
        edge = fair_value - market_price
        scaled_edge = edge * temporal_factor
        fee_adjusted_edge = scaled_edge - market.fee_rate

        # Recommendation
        recommendation = self._recommend(fee_adjusted_edge, confidence)

        result = ValuationResult(
            market_id=market.id,
            fair_value=round(fair_value, 4),
            market_price=market_price,
            edge=round(edge, 4),
            confidence=round(confidence, 4),
            fee_adjusted_edge=round(fee_adjusted_edge, 4),
            recommendation=recommendation,
            edge_sources=edge_sources,
            timestamp=datetime.now(tz=UTC),
            inputs=inputs,
        )

        logger.info(
            "market_assessed",
            market_id=market.id,
            fair_value=result.fair_value,
            market_price=market_price,
            edge=result.edge,
            fee_adjusted_edge=result.fee_adjusted_edge,
            confidence=result.confidence,
            recommendation=result.recommendation,
        )

        return result

    async def assess_batch(
        self,
        markets: list[Market],
        *,
        universe: list[Market] | None = None,
        max_concurrent: int = 10,
        external_signals: dict[str, dict[str, Any]] | None = None,
    ) -> list[ValuationResult]:
        """Assess multiple markets concurrently.

        Markets are assessed in parallel with a concurrency limit.
        Prioritizes by volume (higher volume = assessed first).
        """
        # Sort by volume descending (most liquid first)
        sorted_markets = sorted(markets, key=lambda m: m.volume, reverse=True)

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _assess_one(m: Market) -> ValuationResult:
            async with semaphore:
                extra: dict[str, Any] = (external_signals or {}).get(m.id, {})
                return await self.assess(m, universe=universe or markets, **extra)

        results = await asyncio.gather(
            *[_assess_one(m) for m in sorted_markets],
            return_exceptions=True,
        )

        # Filter out exceptions, log them
        valid_results: list[ValuationResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "assess_failed",
                    market_id=sorted_markets[i].id,
                    error=str(result),
                )
            else:
                valid_results.append(result)

        # Sort by absolute fee-adjusted edge (most interesting first)
        valid_results.sort(key=lambda r: abs(r.fee_adjusted_edge), reverse=True)

        logger.info(
            "batch_assessed",
            total=len(markets),
            successful=len(valid_results),
            with_edge=sum(
                1
                for r in valid_results
                if abs(r.fee_adjusted_edge) > self._thresholds.min_edge
            ),
        )

        return valid_results

    def _compute_fair_value(
        self, inputs: ValuationInput
    ) -> tuple[float, list[EdgeSource], float]:
        """Compute weighted fair value from all inputs.

        Returns (fair_value, edge_sources, confidence).
        """
        sources: list[EdgeSource] = []
        weighted_sum = 0.0
        weight_total = 0.0
        confidence_sum = 0.0
        source_count = 0

        # Base rate
        if inputs.base_rate is not None:
            w = self._weights.base_rate
            weighted_sum += w * inputs.base_rate
            weight_total += w
            sources.append(
                EdgeSource(
                    name="base_rate",
                    contribution=round(inputs.base_rate - inputs.market_price, 4),
                    confidence=0.5,  # moderate confidence in historical rates
                    detail=f"Historical base rate: {inputs.base_rate:.3f}",
                )
            )
            confidence_sum += 0.5
            source_count += 1

        # Crowd calibration (modifies market price, not an independent signal)
        if inputs.crowd_calibration_adjustment != 0:
            adjusted_price = inputs.market_price + inputs.crowd_calibration_adjustment
            sources.append(
                EdgeSource(
                    name="crowd_calibration",
                    contribution=round(inputs.crowd_calibration_adjustment, 4),
                    confidence=0.4,
                    detail=f"Calibration adj: {inputs.crowd_calibration_adjustment:+.3f}",
                )
            )
            # Add calibration as a weighted signal toward adjusted price
            w = self._weights.crowd_calibration
            weighted_sum += w * adjusted_price
            weight_total += w
            confidence_sum += 0.4
            source_count += 1

        # Rule analysis
        if inputs.rule_analysis_score is not None:
            w = self._weights.rule_analysis
            # Rule score: 0-1 where 1 = clearly favorable resolution
            rule_signal = inputs.rule_analysis_score
            weighted_sum += w * rule_signal
            weight_total += w
            conf = 0.6 if rule_signal > 0.7 else 0.3
            sources.append(
                EdgeSource(
                    name="rule_analysis",
                    contribution=round(rule_signal - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"Rule clarity: {rule_signal:.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Microstructure
        if inputs.microstructure_score is not None:
            w = self._weights.microstructure
            # Microstructure score is 0-1, center around market price
            # High micro score = market is active and interesting
            micro_signal = inputs.market_price + (inputs.microstructure_score - 0.5) * 0.1
            micro_signal = max(0, min(1, micro_signal))
            weighted_sum += w * micro_signal
            weight_total += w
            conf = 0.4
            sources.append(
                EdgeSource(
                    name="microstructure",
                    contribution=round(micro_signal - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"Micro score: {inputs.microstructure_score:.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Cross-market signal
        if inputs.cross_market_signal is not None:
            w = self._weights.cross_market
            # Signal is -1 to +1, translate to probability adjustment
            cross_prob = inputs.market_price + inputs.cross_market_signal * 0.15
            cross_prob = max(0, min(1, cross_prob))
            weighted_sum += w * cross_prob
            weight_total += w
            conf = 0.5 if abs(inputs.cross_market_signal) > 0.3 else 0.2
            sources.append(
                EdgeSource(
                    name="cross_market",
                    contribution=round(cross_prob - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"Cross-market signal: {inputs.cross_market_signal:+.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Event signal (from intelligence pipeline -- will be None until Phase 3)
        if inputs.event_signal is not None:
            w = self._weights.event_signal
            event_prob = max(0, min(1, inputs.event_signal))
            weighted_sum += w * event_prob
            weight_total += w
            conf = 0.7 if abs(event_prob - inputs.market_price) > 0.1 else 0.3
            sources.append(
                EdgeSource(
                    name="event_signal",
                    contribution=round(event_prob - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"Event signal: {event_prob:.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Pattern/KG signal (from Obsidian -- will be None until Phase 3)
        if inputs.pattern_kg_signal is not None:
            w = self._weights.pattern_kg
            pattern_prob = max(0, min(1, inputs.pattern_kg_signal))
            weighted_sum += w * pattern_prob
            weight_total += w
            conf = 0.5
            sources.append(
                EdgeSource(
                    name="pattern_kg",
                    contribution=round(pattern_prob - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"KG pattern signal: {pattern_prob:.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Cross-platform signal (from Manifold satellite)
        if inputs.cross_platform_signal is not None:
            w = self._weights.cross_platform
            cp_prob = max(0, min(1, inputs.cross_platform_signal))
            weighted_sum += w * cp_prob
            weight_total += w
            divergence = abs(cp_prob - inputs.market_price)
            conf = 0.6 if divergence > 0.1 else 0.3
            sources.append(
                EdgeSource(
                    name="cross_platform",
                    contribution=round(cp_prob - inputs.market_price, 4),
                    confidence=conf,
                    detail=f"Manifold signal: {cp_prob:.3f}",
                )
            )
            confidence_sum += conf
            source_count += 1

        # Temporal factor is NOT a probability source -- it scales the edge later

        # Compute fair value
        if weight_total == 0:
            # No signals at all -- fair value is market price (no edge)
            return inputs.market_price, sources, 0.0

        fair_value = weighted_sum / weight_total
        fair_value = max(0.0, min(1.0, fair_value))

        # Confidence: average of source confidences, with gentle coverage scaling.
        # Old formula (coverage = count/5) was too harsh — with 1-2 sources active
        # in early operation, it crushed confidence below min_confidence (0.3),
        # making the bot permanently inactive.
        # New: floor at 0.5 so even a single strong source can produce actionable edge.
        coverage = min(1.0, 0.5 + source_count / 6)  # 1 src → 0.67, 3 → 1.0
        avg_confidence = confidence_sum / source_count if source_count > 0 else 0.0
        confidence = avg_confidence * coverage

        return round(fair_value, 4), sources, round(confidence, 4)

    def _recommend(self, fee_adjusted_edge: float, confidence: float) -> Recommendation:
        """Determine recommendation based on edge and confidence."""
        if confidence < self._thresholds.min_confidence:
            return Recommendation.HOLD  # not confident enough

        if fee_adjusted_edge >= self._thresholds.strong_edge:
            return Recommendation.STRONG_BUY
        elif fee_adjusted_edge >= self._thresholds.min_edge:
            return Recommendation.BUY
        elif fee_adjusted_edge <= -self._thresholds.strong_edge:
            return Recommendation.STRONG_SELL
        elif fee_adjusted_edge <= -self._thresholds.min_edge:
            return Recommendation.SELL
        else:
            return Recommendation.HOLD

    @staticmethod
    def _get_market_price(market: Market) -> float:
        """Get the YES outcome price from a market."""
        for outcome in market.outcomes:
            if outcome.outcome.lower() == "yes":
                return outcome.price
        return 0.5  # default if no YES outcome found

    def _analyze_microstructure(
        self, orderbook: OrderBook | None, history: PriceHistory | None
    ) -> float:
        """Run microstructure analysis and return composite score."""
        ob_analysis = MicrostructureAnalysis()
        hist_analysis = MicrostructureAnalysis()

        if isinstance(orderbook, OrderBook):
            ob_analysis = self._microstructure.analyze_orderbook(orderbook)
        if isinstance(history, PriceHistory):
            hist_analysis = self._microstructure.analyze_price_history(history)

        composite = self._microstructure.compute_composite(ob_analysis, hist_analysis)
        return composite.composite_score
