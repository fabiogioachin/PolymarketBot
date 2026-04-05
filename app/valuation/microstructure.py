"""Market microstructure analyzer: orderbook, volume, and market dynamics analysis."""

from dataclasses import dataclass
from datetime import timedelta

from app.core.logging import get_logger
from app.models.market import OrderBook, OrderBookLevel, PriceHistory, PricePoint

logger = get_logger(__name__)


@dataclass
class MicrostructureAnalysis:
    """Result of microstructure analysis for a single market."""

    spread_pct: float = 0.0  # bid-ask spread as % of midpoint
    depth_imbalance: float = 0.0  # -1 to +1 (negative=sell pressure, positive=buy pressure)
    total_bid_depth: float = 0.0  # total $ on bid side
    total_ask_depth: float = 0.0  # total $ on ask side
    liquidity_score: float = 0.0  # 0-1, how easy to enter/exit
    volume_anomaly: float = 0.0  # ratio of recent volume to baseline (>2 = anomaly)
    momentum_1h: float = 0.0  # price change over 1 hour
    momentum_24h: float = 0.0  # price change over 24 hours
    momentum_7d: float = 0.0  # price change over 7 days
    composite_score: float = 0.0  # 0-1, overall microstructure signal


class MicrostructureAnalyzer:
    """Analyzes market microstructure from orderbook and price data."""

    def analyze_orderbook(self, orderbook: OrderBook) -> MicrostructureAnalysis:
        """Analyze a single orderbook snapshot."""
        analysis = MicrostructureAnalysis()

        if not orderbook.bids and not orderbook.asks:
            return analysis

        # Spread analysis
        analysis.spread_pct = self._compute_spread_pct(orderbook)

        # Depth analysis
        analysis.total_bid_depth = self._sum_depth(orderbook.bids)
        analysis.total_ask_depth = self._sum_depth(orderbook.asks)
        analysis.depth_imbalance = self._compute_imbalance(
            analysis.total_bid_depth, analysis.total_ask_depth
        )

        # Liquidity score: combination of spread tightness and depth
        analysis.liquidity_score = self._compute_liquidity_score(
            analysis.spread_pct, analysis.total_bid_depth + analysis.total_ask_depth
        )

        return analysis

    def analyze_price_history(
        self, history: PriceHistory, baseline_days: int = 7
    ) -> MicrostructureAnalysis:
        """Analyze price history for momentum and volume anomalies."""
        analysis = MicrostructureAnalysis()

        if not history.points or len(history.points) < 2:
            return analysis

        points = sorted(history.points, key=lambda p: p.timestamp)
        current_price = points[-1].price

        # Momentum calculations
        analysis.momentum_1h = self._compute_momentum(points, hours=1, current=current_price)
        analysis.momentum_24h = self._compute_momentum(points, hours=24, current=current_price)
        analysis.momentum_7d = self._compute_momentum(points, hours=168, current=current_price)

        # Volume anomaly
        analysis.volume_anomaly = self._compute_volume_anomaly(points, baseline_days)

        return analysis

    def compute_composite(
        self,
        orderbook_analysis: MicrostructureAnalysis,
        history_analysis: MicrostructureAnalysis,
    ) -> MicrostructureAnalysis:
        """Merge orderbook and history analysis into a single composite analysis."""
        composite = MicrostructureAnalysis(
            spread_pct=orderbook_analysis.spread_pct,
            depth_imbalance=orderbook_analysis.depth_imbalance,
            total_bid_depth=orderbook_analysis.total_bid_depth,
            total_ask_depth=orderbook_analysis.total_ask_depth,
            liquidity_score=orderbook_analysis.liquidity_score,
            volume_anomaly=history_analysis.volume_anomaly,
            momentum_1h=history_analysis.momentum_1h,
            momentum_24h=history_analysis.momentum_24h,
            momentum_7d=history_analysis.momentum_7d,
        )

        # Composite score: weighted combination
        # Higher is better for trading opportunity
        score = 0.0

        # Tight spread is good (invert: lower spread = higher score)
        spread_score = max(0, 1 - composite.spread_pct * 10)  # 10% spread = 0 score
        score += 0.25 * spread_score

        # Good liquidity is good
        score += 0.25 * composite.liquidity_score

        # Volume anomaly can signal information (interesting, not strictly good/bad)
        anomaly_signal = (
            min(1.0, composite.volume_anomaly / 3.0) if composite.volume_anomaly > 1 else 0
        )
        score += 0.20 * anomaly_signal

        # Strong imbalance signals directional pressure
        score += 0.15 * abs(composite.depth_imbalance)

        # Momentum signals trend
        momentum_signal = min(1.0, abs(composite.momentum_24h) * 10)
        score += 0.15 * momentum_signal

        composite.composite_score = round(min(1.0, max(0.0, score)), 4)
        return composite

    @staticmethod
    def _compute_spread_pct(orderbook: OrderBook) -> float:
        if orderbook.midpoint <= 0:
            return 0.0
        return orderbook.spread / orderbook.midpoint

    @staticmethod
    def _sum_depth(levels: list[OrderBookLevel]) -> float:
        return sum(level.price * level.size for level in levels)

    @staticmethod
    def _compute_imbalance(bid_depth: float, ask_depth: float) -> float:
        total = bid_depth + ask_depth
        if total == 0:
            return 0.0
        return (bid_depth - ask_depth) / total

    @staticmethod
    def _compute_liquidity_score(spread_pct: float, total_depth: float) -> float:
        # Tight spread (< 5%) and deep book (> $10k) = high score
        spread_component = max(0, 1 - spread_pct / 0.05)  # 5% spread = 0
        depth_component = min(1.0, total_depth / 10000)  # $10k = max score
        return round(0.6 * spread_component + 0.4 * depth_component, 4)

    @staticmethod
    def _compute_momentum(points: list[PricePoint], hours: int, current: float) -> float:
        """Compute price change over specified hours."""
        if not points:
            return 0.0
        target_time = points[-1].timestamp - timedelta(hours=hours)
        # Find closest point to target time
        closest = min(points, key=lambda p: abs((p.timestamp - target_time).total_seconds()))
        if closest.price == 0:
            return 0.0
        return (current - closest.price) / closest.price

    @staticmethod
    def _compute_volume_anomaly(points: list[PricePoint], baseline_days: int) -> float:
        """Compare recent volume to baseline average."""
        if len(points) < 2:
            return 0.0

        now = points[-1].timestamp
        baseline_start = now - timedelta(days=baseline_days)
        recent_start = now - timedelta(days=1)

        baseline_points = [p for p in points if baseline_start <= p.timestamp < recent_start]
        recent_points = [p for p in points if p.timestamp >= recent_start]

        if not baseline_points or not recent_points:
            return 0.0

        baseline_avg = sum(p.volume for p in baseline_points) / len(baseline_points)
        recent_avg = sum(p.volume for p in recent_points) / len(recent_points)

        if baseline_avg == 0:
            return 0.0
        return round(recent_avg / baseline_avg, 4)
