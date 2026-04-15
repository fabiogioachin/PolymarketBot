"""Tests for position_monitor.evaluate_exit()."""

from datetime import UTC, datetime, timedelta

import pytest

from app.execution.position_monitor import ExitDecision, evaluate_exit
from app.models.market import Market
from app.models.order import OrderSide, Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
    *,
    avg_price: float = 0.05,
    current_price: float = 0.017,
    size: float = 100.0,
    token_id: str = "tok-1",
    market_id: str = "mkt-1",
) -> Position:
    return Position(
        token_id=token_id,
        market_id=market_id,
        side=OrderSide.BUY,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
    )


def _make_market(*, end_date: datetime, market_id: str = "mkt-1") -> Market:
    return Market(
        id=market_id,
        question="Test market",
        end_date=end_date,
    )


# ---------------------------------------------------------------------------
# Test: expired market (end_date in the past) → force exit, urgency=1.0
# ---------------------------------------------------------------------------


class TestExpiredMarketForceExit:
    def test_expired_2_days_ago_sub_10_cent_price_exits(self) -> None:
        """Expired market with sub-10-cent price must be force-exited."""
        end_date = datetime.now(tz=UTC) - timedelta(days=2)
        position = _make_position(avg_price=0.05, current_price=0.017)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is True
        assert result.urgency == 1.0
        assert "expired" in result.reason.lower()
        assert "force exit" in result.reason.lower()

    def test_expired_market_mid_range_price_also_exits(self) -> None:
        """Even a mid-range price (e.g. 0.50) on an expired market must be exited."""
        end_date = datetime.now(tz=UTC) - timedelta(days=1)
        position = _make_position(avg_price=0.40, current_price=0.50)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is True
        assert result.urgency == 1.0

    def test_expired_just_now_exits(self) -> None:
        """A market that expired mere seconds ago also gets force-exited."""
        end_date = datetime.now(tz=UTC) - timedelta(seconds=5)
        position = _make_position(avg_price=0.05, current_price=0.05)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is True
        assert result.urgency == 1.0

    def test_reason_contains_end_date(self) -> None:
        """The reason string must include the end_date for operator visibility."""
        end_date = datetime.now(tz=UTC) - timedelta(days=2)
        position = _make_position(avg_price=0.05, current_price=0.017)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert end_date.strftime("%Y-%m-%d") in result.reason


# ---------------------------------------------------------------------------
# Test: market expiring in 1 hour with price=0.05 → existing collapse logic
# ---------------------------------------------------------------------------


class TestNearExpiryCollapseLogicStillWorks:
    def test_price_collapsed_near_expiry_triggers_exit(self) -> None:
        """Near-expiry collapse check: price dropped 50%+ from entry and < 0.05."""
        end_date = datetime.now(tz=UTC) + timedelta(hours=1)
        # entry=0.15, current=0.04 → dropped >50% and absolute < 0.05
        position = _make_position(avg_price=0.15, current_price=0.04)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is True
        assert result.urgency == 0.9
        assert "collapsed" in result.reason.lower()

    def test_flat_low_price_near_expiry_no_collapse_does_not_exit(self) -> None:
        """Long-shot bet (always low price, not collapsed) near expiry: no exit."""
        end_date = datetime.now(tz=UTC) + timedelta(hours=1)
        # entry=0.05, current=0.05 — price didn't drop significantly (not collapsed)
        position = _make_position(avg_price=0.05, current_price=0.05)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        # 0.05 < 0.10 so the flatten band (0.10-0.80) does NOT trigger.
        # entry == current so collapse does NOT trigger.
        assert result.should_exit is False

    def test_mid_range_price_near_expiry_flattens(self) -> None:
        """Mid-range price (0.10-0.80) near expiry triggers the flatten band."""
        end_date = datetime.now(tz=UTC) + timedelta(hours=1)
        position = _make_position(avg_price=0.30, current_price=0.35)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is True
        assert result.urgency == 0.7
        assert "flattening" in result.reason.lower()


# ---------------------------------------------------------------------------
# Test: future market (5 days out) → no force-exit, normal logic
# ---------------------------------------------------------------------------


class TestFutureMarketNoForceExit:
    def test_future_market_no_exit_on_low_price(self) -> None:
        """Active market 5 days from expiry with sub-10-cent price: no exit."""
        end_date = datetime.now(tz=UTC) + timedelta(days=5)
        position = _make_position(avg_price=0.05, current_price=0.017)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is False

    def test_future_market_returns_empty_decision(self) -> None:
        """No triggers met on a healthy future position returns default ExitDecision."""
        end_date = datetime.now(tz=UTC) + timedelta(days=5)
        position = _make_position(avg_price=0.30, current_price=0.32)
        market = _make_market(end_date=end_date)

        result = evaluate_exit(position, market=market)

        assert result.should_exit is False
        assert result.urgency == 0.0


# ---------------------------------------------------------------------------
# Test: market=None guard still works
# ---------------------------------------------------------------------------


class TestNullMarketGuard:
    def test_no_market_no_exit_on_normal_position(self) -> None:
        """When market is None the expiry block is skipped entirely."""
        position = _make_position(avg_price=0.30, current_price=0.32)

        result = evaluate_exit(position, market=None)

        assert result.should_exit is False

    def test_no_market_take_profit_still_fires(self) -> None:
        """Take-profit trigger works even without a market object."""
        # entry=0.20, current=0.35 → ratio 1.75 >= 1.5
        position = _make_position(avg_price=0.20, current_price=0.35)

        result = evaluate_exit(position, market=None)

        assert result.should_exit is True
        assert result.urgency == 0.6
        assert "take profit" in result.reason.lower()
