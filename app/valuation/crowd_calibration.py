"""Crowd calibration: how well-calibrated is the prediction market crowd?"""

from app.core.logging import get_logger
from app.models.market import MarketCategory
from app.models.valuation import CalibrationData, CalibrationPoint
from app.valuation.db import ResolutionDB

logger = get_logger(__name__)

# Probability buckets for calibration curve
_BUCKETS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_BUCKET_WIDTH = 0.1


class CrowdCalibrationAnalyzer:
    """Analyzes how well-calibrated market prices are as probability estimates."""

    def __init__(self, db: ResolutionDB) -> None:
        self._db = db
        self._calibrations: dict[str, CalibrationData] = {}

    async def compute_calibration(
        self, category: str | None = None
    ) -> CalibrationData:
        """Compute calibration curve for a category (or all if None)."""
        resolutions = await self._db.get_resolutions(category=category)

        if not resolutions:
            return CalibrationData(
                category=category or "all",
                sample_size=0,
            )

        points: list[CalibrationPoint] = []
        total_bias = 0.0
        total_samples = 0

        for bucket_center in _BUCKETS:
            low = bucket_center - _BUCKET_WIDTH / 2
            high = bucket_center + _BUCKET_WIDTH / 2

            in_bucket = [r for r in resolutions if low <= r.final_price < high]

            if not in_bucket:
                continue

            actual_yes = sum(1 for r in in_bucket if r.resolved_yes)
            actual_freq = actual_yes / len(in_bucket)

            points.append(
                CalibrationPoint(
                    predicted_probability=bucket_center,
                    actual_frequency=actual_freq,
                    sample_size=len(in_bucket),
                )
            )

            # Bias: positive means crowd overconfident (prices too high for YES)
            bias_contribution = (bucket_center - actual_freq) * len(in_bucket)
            total_bias += bias_contribution
            total_samples += len(in_bucket)

        overall_bias = total_bias / total_samples if total_samples > 0 else 0.0

        calibration = CalibrationData(
            category=category or "all",
            points=points,
            bias=round(overall_bias, 4),
            sample_size=total_samples,
        )

        if category:
            self._calibrations[category] = calibration

        logger.info(
            "calibration_computed",
            category=category or "all",
            bias=calibration.bias,
            samples=total_samples,
        )
        return calibration

    async def get_adjustment(self, category: str) -> float:
        """Get the calibration adjustment for a category.

        Returns a value to ADD to the market price to correct for crowd bias.
        If crowd is overconfident (bias > 0), returns negative adjustment.
        If crowd is underconfident (bias < 0), returns positive adjustment.
        """
        if category not in self._calibrations:
            await self.compute_calibration(category=category)

        cal = self._calibrations.get(category)
        if cal is None or cal.sample_size < 20:
            return 0.0  # not enough data to make an adjustment

        # Negate bias: if crowd overestimates (bias>0), we adjust DOWN
        return -cal.bias

    async def compute_all_categories(self) -> dict[str, CalibrationData]:
        """Compute calibration for all market categories."""
        results: dict[str, CalibrationData] = {}
        for cat in MarketCategory:
            cal = await self.compute_calibration(category=cat.value)
            results[cat.value] = cal
        self._calibrations = results
        return results
