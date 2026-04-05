"""Tests for circuit breaker."""

from datetime import UTC, datetime, timedelta

from app.risk.circuit_breaker import CircuitBreaker, CircuitBreakerState


class TestCircuitBreakerInit:
    def test_initial_state_not_tripped(self) -> None:
        cb = CircuitBreaker()
        state = cb.state
        assert state.is_tripped is False
        assert state.reason == ""
        assert state.tripped_at is None
        assert state.consecutive_losses == 0

    def test_initialize_sets_capital(self) -> None:
        cb = CircuitBreaker()
        cb.initialize(150.0)
        state = cb.state
        assert state.daily_drawdown_pct == 0.0
        assert state.is_tripped is False


class TestConsecutiveLosses:
    def test_trip_after_3_consecutive_losses(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.initialize(150.0)

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is False
        assert cb.state.consecutive_losses == 1

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is False
        assert cb.state.consecutive_losses == 2

        state = cb.record_trade_result(-5.0)
        assert state.is_tripped is True
        assert state.consecutive_losses == 3
        assert "Consecutive losses" in state.reason

    def test_reset_consecutive_losses_on_win(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.initialize(150.0)

        cb.record_trade_result(-5.0)
        cb.record_trade_result(-5.0)
        assert cb.state.consecutive_losses == 2

        cb.record_trade_result(3.0)
        assert cb.state.consecutive_losses == 0
        assert cb.state.is_tripped is False

    def test_mixed_wins_losses_dont_trip(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.initialize(150.0)

        # Alternating loss/win pattern never reaches 3 consecutive
        for _ in range(10):
            cb.record_trade_result(-2.0)
            cb.record_trade_result(1.0)

        assert cb.state.is_tripped is False
        assert cb.state.consecutive_losses == 0


class TestDrawdown:
    def test_trip_on_15pct_daily_drawdown(self) -> None:
        cb = CircuitBreaker(max_daily_drawdown_pct=15.0, max_consecutive_losses=100)
        cb.initialize(100.0)

        # Single large loss that triggers 15% drawdown
        state = cb.record_trade_result(-15.0)
        assert state.is_tripped is True
        assert "Daily drawdown" in state.reason
        assert state.daily_drawdown_pct >= 15.0

    def test_drawdown_calculation_correct(self) -> None:
        cb = CircuitBreaker(max_daily_drawdown_pct=20.0, max_consecutive_losses=100)
        cb.initialize(200.0)

        cb.record_trade_result(-20.0)
        state = cb.state
        # (200 - 180) / 200 * 100 = 10%
        assert state.daily_drawdown_pct == 10.0
        assert state.is_tripped is False


class TestCooldown:
    def test_remains_tripped_within_cooldown(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=60)
        cb.initialize(100.0)

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is True

        # Still tripped (cooldown not elapsed)
        state = cb.check()
        assert state.is_tripped is True
        assert state.cooldown_until is not None

    def test_reset_after_cooldown_expires(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=60)
        cb.initialize(100.0)

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is True

        # Simulate time passing beyond cooldown
        past_time = datetime.now(tz=UTC) - timedelta(minutes=120)
        cb._tripped_at = past_time

        state = cb.check()
        assert state.is_tripped is False


class TestReset:
    def test_reset_clears_state(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1)
        cb.initialize(100.0)

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is True

        cb.reset()
        state = cb.state
        assert state.is_tripped is False
        assert state.reason == ""
        assert state.tripped_at is None
        assert state.consecutive_losses == 0

    def test_reset_daily_resets_everything(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1)
        cb.initialize(100.0)

        cb.record_trade_result(-5.0)
        assert cb.state.is_tripped is True

        cb.reset_daily(200.0)
        state = cb.state
        assert state.is_tripped is False
        assert state.consecutive_losses == 0
        assert state.daily_drawdown_pct == 0.0


class TestStateProperty:
    def test_state_returns_correct_values(self) -> None:
        cb = CircuitBreaker(
            max_consecutive_losses=5, max_daily_drawdown_pct=20.0, cooldown_minutes=30
        )
        cb.initialize(100.0)

        cb.record_trade_result(-10.0)
        cb.record_trade_result(-5.0)

        state = cb.state
        assert isinstance(state, CircuitBreakerState)
        assert state.consecutive_losses == 2
        assert state.daily_drawdown_pct == 15.0
        assert state.is_tripped is False

    def test_state_cooldown_until_set_when_tripped(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=45)
        cb.initialize(100.0)

        cb.record_trade_result(-5.0)
        state = cb.state
        assert state.cooldown_until is not None
        assert state.tripped_at is not None
        expected_cooldown = state.tripped_at + timedelta(minutes=45)
        assert state.cooldown_until == expected_cooldown
