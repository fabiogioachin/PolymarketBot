"""Tests for app.valuation.insider_pressure (Phase 13 S4b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.intelligence import WhaleTrade
from app.models.market import Market, MarketCategory, MarketStatus, Outcome
from app.valuation.insider_pressure import compute_insider_pressure


def _market(
    market_id: str = "m1",
    yes_price: float = 0.50,
    category: MarketCategory = MarketCategory.POLITICS,
) -> Market:
    return Market(
        id=market_id,
        question="Will X happen?",
        category=category,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=round(1.0 - yes_price, 4)),
        ],
        end_date=datetime.now(tz=UTC) + timedelta(hours=2),
    )


def _trade(
    *,
    side: str = "BUY",
    size_usd: float = 1_500_000.0,
    is_pre_resolution: bool = True,
    total_pnl: float | None = None,
    weekly_pnl: float | None = None,
    volume_rank: int | None = None,
    wallet: str = "0xinsider",
    market_id: str = "m1",
) -> WhaleTrade:
    return WhaleTrade(
        id=f"t-{side}-{size_usd:.0f}-{wallet}",
        timestamp=datetime.now(tz=UTC),
        market_id=market_id,
        wallet_address=wallet,
        side=side,
        size_usd=size_usd,
        price=0.5,
        is_pre_resolution=is_pre_resolution,
        wallet_total_pnl=total_pnl,
        wallet_weekly_pnl=weekly_pnl,
        wallet_volume_rank=volume_rank,
    )


class TestComputeInsiderPressure:
    def test_empty_returns_neutral(self) -> None:
        market = _market()
        assert compute_insider_pressure(market, [], market_price=0.5) == 0.5

    def test_obvious_high_outcome_returns_neutral(self) -> None:
        # Price already ≥ 0.95 → no insider signal regardless of trades.
        market = _market(yes_price=0.97)
        trades = [_trade(side="BUY", size_usd=2_000_000.0)]
        assert compute_insider_pressure(market, trades, market_price=0.97) == 0.5

    def test_obvious_low_outcome_returns_neutral(self) -> None:
        market = _market(yes_price=0.03)
        trades = [_trade(side="SELL", size_usd=2_000_000.0)]
        assert compute_insider_pressure(market, trades, market_price=0.03) == 0.5

    def test_no_pre_resolution_returns_neutral(self) -> None:
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                is_pre_resolution=False,
                total_pnl=1_000_000.0,
            )
        ]
        assert compute_insider_pressure(market, trades, market_price=0.5) == 0.5

    def test_single_match_not_enough_to_escalate(self) -> None:
        # Only ONE criterion met (high pnl alone, size just $150k) → below
        # the _ESCALATION_MIN_MATCHES threshold → neutral.
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="BUY",
                size_usd=150_000.0,
                total_pnl=1_000_000.0,
            )
        ]
        assert compute_insider_pressure(market, trades, market_price=0.5) == 0.5

    def test_high_pnl_wallet_with_extreme_size_buy_escalates_up(self) -> None:
        # 2 criteria: high pnl AND extreme size → qualifies as insider.
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                total_pnl=1_000_000.0,
            )
        ]
        signal = compute_insider_pressure(market, trades, market_price=0.5)
        assert signal >= 0.7
        assert signal <= 1.0

    def test_unknown_wallet_extreme_size_sell_escalates_down(self) -> None:
        # Fresh wallet + $1M+ + pre-res + SELL → 3 criteria → strong SELL.
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="SELL",
                size_usd=2_000_000.0,
                total_pnl=None,
                weekly_pnl=None,
                volume_rank=None,
            )
        ]
        signal = compute_insider_pressure(market, trades, market_price=0.5)
        assert signal <= 0.3 + 1e-9
        assert signal >= 0.0

    def test_balanced_buy_and_sell_insiders_neutral(self) -> None:
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                total_pnl=1_000_000.0,
                wallet="0xa",
            ),
            _trade(
                side="SELL",
                size_usd=2_000_000.0,
                total_pnl=1_000_000.0,
                wallet="0xb",
            ),
        ]
        signal = compute_insider_pressure(market, trades, market_price=0.5)
        assert signal == 0.5

    def test_multiple_buys_increase_intensity(self) -> None:
        market = _market(yes_price=0.5)
        one = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                total_pnl=1_000_000.0,
                wallet="0xa",
            )
        ]
        three = one + [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                total_pnl=1_000_000.0,
                wallet=f"0x{i}",
            )
            for i in range(2)
        ]
        sig_one = compute_insider_pressure(market, one, market_price=0.5)
        sig_three = compute_insider_pressure(market, three, market_price=0.5)
        assert sig_three >= sig_one

    def test_signal_always_bounded(self) -> None:
        market = _market(yes_price=0.5)
        trades = [
            _trade(
                side="BUY",
                size_usd=5_000_000.0,
                total_pnl=10_000_000.0,
                wallet=f"0x{i}",
            )
            for i in range(50)
        ]
        signal = compute_insider_pressure(market, trades, market_price=0.5)
        assert 0.0 <= signal <= 1.0
