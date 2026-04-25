"""Tests for app.valuation.whale_pressure (Phase 13 S4b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.intelligence import WhaleTrade
from app.valuation.whale_pressure import compute_whale_pressure


def _trade(
    *,
    side: str = "BUY",
    size_usd: float = 150_000.0,
    ts: datetime | None = None,
    market_id: str = "m1",
    wallet: str = "0xwhale",
    total_pnl: float | None = None,
    weekly_pnl: float | None = None,
    volume_rank: int | None = None,
) -> WhaleTrade:
    return WhaleTrade(
        id=f"t-{side}-{size_usd:.0f}-{wallet}",
        timestamp=ts or datetime.now(tz=UTC),
        market_id=market_id,
        wallet_address=wallet,
        side=side,
        size_usd=size_usd,
        price=0.5,
        is_pre_resolution=False,
        wallet_total_pnl=total_pnl,
        wallet_weekly_pnl=weekly_pnl,
        wallet_volume_rank=volume_rank,
    )


class TestComputeWhalePressure:
    def test_empty_returns_neutral(self) -> None:
        assert compute_whale_pressure([], market_price=0.5) == 0.5

    def test_below_threshold_returns_neutral(self) -> None:
        # Size below $100k → ignored → neutral
        trades = [_trade(size_usd=50_000.0)]
        assert compute_whale_pressure(trades, market_price=0.5) == 0.5

    def test_single_buy_whale_pushes_above_neutral(self) -> None:
        trades = [_trade(side="BUY", size_usd=200_000.0)]
        signal = compute_whale_pressure(trades, market_price=0.5)
        assert signal > 0.5
        assert signal <= 1.0

    def test_single_sell_whale_pushes_below_neutral(self) -> None:
        trades = [_trade(side="SELL", size_usd=200_000.0)]
        signal = compute_whale_pressure(trades, market_price=0.5)
        assert signal < 0.5
        assert signal >= 0.0

    def test_balanced_buy_sell_returns_neutral(self) -> None:
        trades = [
            _trade(side="BUY", size_usd=200_000.0, wallet="0xa"),
            _trade(side="SELL", size_usd=200_000.0, wallet="0xb"),
        ]
        signal = compute_whale_pressure(trades, market_price=0.5)
        assert abs(signal - 0.5) < 1e-9

    def test_top_volume_wallet_amplifies_signal(self) -> None:
        # Two BUY whales of identical size: one unranked, one top-rank.
        baseline = [
            _trade(side="BUY", size_usd=200_000.0, wallet="0xa"),
            _trade(side="SELL", size_usd=200_000.0, wallet="0xb"),
        ]
        amplified = [
            _trade(
                side="BUY",
                size_usd=200_000.0,
                wallet="0xa",
                volume_rank=50,     # top-10%
            ),
            _trade(side="SELL", size_usd=200_000.0, wallet="0xb"),
        ]
        base_signal = compute_whale_pressure(baseline, market_price=0.5)
        amp_signal = compute_whale_pressure(amplified, market_price=0.5)
        assert amp_signal > base_signal

    def test_high_pnl_wallet_amplifies_signal(self) -> None:
        baseline = [
            _trade(side="BUY", size_usd=200_000.0, wallet="0xa"),
            _trade(side="SELL", size_usd=200_000.0, wallet="0xb"),
        ]
        amplified = [
            _trade(
                side="BUY",
                size_usd=200_000.0,
                wallet="0xa",
                total_pnl=1_000_000.0,
            ),
            _trade(side="SELL", size_usd=200_000.0, wallet="0xb"),
        ]
        assert (
            compute_whale_pressure(amplified, market_price=0.5)
            > compute_whale_pressure(baseline, market_price=0.5)
        )

    def test_unknown_wallet_extreme_size_is_maximum(self) -> None:
        # Unknown wallet (no enrichment) + $1M+ trade → weight 3.0 per D4 (d).
        trades = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                wallet="0xfresh",
                # all enrichment fields None → "unknown wallet"
            )
        ]
        signal = compute_whale_pressure(trades, market_price=0.5)
        # Pure single-side heavy signal lands at the top of the range.
        assert signal > 0.95

    def test_old_trades_outside_lookback_ignored(self) -> None:
        # 10h ago, lookback 6h → ignored → neutral.
        old = datetime.now(tz=UTC) - timedelta(hours=10)
        trades = [_trade(side="BUY", size_usd=500_000.0, ts=old)]
        signal = compute_whale_pressure(
            trades, market_price=0.5, lookback_hours=6
        )
        assert signal == 0.5

    def test_signal_always_bounded(self) -> None:
        # Pile of heavy BUY whales must never overshoot 1.0.
        trades = [
            _trade(
                side="BUY",
                size_usd=2_000_000.0,
                wallet=f"0x{i}",
            )
            for i in range(20)
        ]
        signal = compute_whale_pressure(trades, market_price=0.5)
        assert 0.0 <= signal <= 1.0
