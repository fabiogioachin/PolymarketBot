"""Shadow executor: runs dry-run and live in parallel, compares results."""

from dataclasses import dataclass

from app.core.logging import get_logger
from app.execution.dry_run import DryRunExecutor
from app.execution.live import LiveExecutor
from app.models.order import Balance, OrderRequest, OrderResult, OrderStatus, Position

logger = get_logger(__name__)


@dataclass
class ShadowComparison:
    """Comparison between dry-run and live execution results."""

    order_id: str = ""
    dry_run_status: str = ""
    live_status: str = ""
    dry_run_price: float = 0.0
    live_price: float = 0.0
    price_deviation: float = 0.0
    match: bool = True
    detail: str = ""


class ShadowExecutor:
    """Executes orders in both dry-run and live mode, comparing results.

    In shadow mode:
    - Dry-run order is always executed (simulated)
    - Live order is attempted but any result is logged, not acted upon
    - Comparison is recorded for analysis
    """

    def __init__(self, dry_run: DryRunExecutor, live: LiveExecutor) -> None:
        self._dry = dry_run
        self._live = live
        self._comparisons: list[ShadowComparison] = []

    async def execute(self, order: OrderRequest) -> OrderResult:
        """Execute in shadow mode: dry-run is the primary, live is secondary."""
        # Primary: dry-run (always succeeds in simulation)
        dry_result = await self._dry.execute(order)

        # Secondary: live (may fail, that's OK)
        try:
            live_result = await self._live.execute(order)
        except Exception as exc:  # noqa: BLE001
            live_result = OrderResult(
                status=OrderStatus.REJECTED,
                error=str(exc),
            )

        # Compare
        comparison = ShadowComparison(
            order_id=dry_result.order_id,
            dry_run_status=dry_result.status,
            live_status=live_result.status,
            dry_run_price=dry_result.price,
            live_price=live_result.price,
            price_deviation=abs(dry_result.price - live_result.price),
            match=dry_result.status == live_result.status,
        )
        self._comparisons.append(comparison)

        logger.info(
            "shadow_execution",
            order_id=dry_result.order_id,
            dry_status=dry_result.status,
            live_status=live_result.status,
            match=comparison.match,
        )

        # Return dry-run result (shadow doesn't affect real positions)
        return dry_result

    async def get_positions(self) -> list[Position]:
        """Delegate to dry-run executor."""
        return await self._dry.get_positions()

    async def get_balance(self) -> Balance:
        """Delegate to dry-run executor."""
        return await self._dry.get_balance()

    @property
    def comparisons(self) -> list[ShadowComparison]:
        """Return a snapshot of all recorded comparisons."""
        return list(self._comparisons)


__all__ = ["ShadowComparison", "ShadowExecutor"]
