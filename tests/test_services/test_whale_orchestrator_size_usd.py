"""Tests for WhaleOrchestrator._parse_trade size/USD detection (Slice 3 N4).

Covers the contract that `_parse_trade` interprets `size` (share count)
vs `size_usd` (already-USD notional) explicitly via raw key inspection
rather than via a numeric threshold heuristic.

These tests use a real `WhaleOrchestrator` instance (no mocking of the
class under test) and exercise the synchronous `_parse_trade` directly —
no HTTP calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.market import Market, MarketCategory, MarketStatus, Outcome
from app.services.whale_orchestrator import WhaleOrchestrator


def _make_market(
    market_id: str = "m_test",
    end_in: timedelta = timedelta(hours=1),
) -> Market:
    """Build a minimal real Market for `_parse_trade` consumption."""
    now = datetime.now(tz=UTC)
    return Market(
        id=market_id,
        question="Q?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=0.5),
            Outcome(token_id="t2", outcome="No", price=0.5),
        ],
        end_date=now + end_in,
        volume=10000.0,
        liquidity=5000.0,
    )


def _make_orchestrator() -> WhaleOrchestrator:
    """Real orchestrator instance — no trades_client interaction needed
    because `_parse_trade` is a pure dict→model transform."""
    return WhaleOrchestrator()


def test_size_field_share_count_large() -> None:
    """`size` (share count) must be multiplied by `price` to get USD.

    Pre-fix (buggy heuristic `size_usd < 1.0`): returned 10000.0 directly
    because 10000 >= 1.0.  Post-fix: explicit shares-vs-usd branching
    yields 10000 * 0.05 = 500.0.
    """
    orch = _make_orchestrator()
    now = datetime.now(tz=UTC)
    market = _make_market()
    raw: dict[str, Any] = {
        "size": 10000,
        "price": 0.05,
        "id": "trade_1",
        "taker": "0xabc",
        "timestamp": now.isoformat(),
        "side": "BUY",
    }

    parsed = orch._parse_trade(raw, market, now, window_min=60)

    assert parsed is not None
    assert parsed.size_usd == 500.0
    assert parsed.id == "trade_1"
    assert parsed.wallet_address == "0xabc"
    assert parsed.side == "BUY"
    assert parsed.price == 0.05


def test_size_usd_field_already_usd() -> None:
    """`size_usd` is already in USD — no multiplication by price."""
    orch = _make_orchestrator()
    now = datetime.now(tz=UTC)
    market = _make_market()
    raw: dict[str, Any] = {
        "size_usd": 25000,
        "price": 0.50,
        "id": "trade_2",
        "taker": "0xdef",
        "timestamp": now.isoformat(),
        "side": "SELL",
    }

    parsed = orch._parse_trade(raw, market, now, window_min=60)

    assert parsed is not None
    assert parsed.size_usd == 25000.0
    assert parsed.id == "trade_2"
    assert parsed.wallet_address == "0xdef"
    assert parsed.side == "SELL"
    assert parsed.price == 0.50


def test_size_field_sub_share_legacy_case() -> None:
    """Sub-share `size` fractions still multiply correctly: 0.5 * 0.10 = 0.05.

    Preserves the historical case the old `< 1.0` heuristic happened to
    handle correctly — explicit branching must not regress it.
    """
    orch = _make_orchestrator()
    now = datetime.now(tz=UTC)
    market = _make_market()
    raw: dict[str, Any] = {
        "size": 0.5,
        "price": 0.10,
        "id": "trade_3",
        "taker": "0xghi",
        "timestamp": now.isoformat(),
        "side": "BUY",
    }

    parsed = orch._parse_trade(raw, market, now, window_min=60)

    assert parsed is not None
    assert parsed.size_usd == 0.05
    assert parsed.id == "trade_3"
    assert parsed.wallet_address == "0xghi"
    assert parsed.side == "BUY"
    assert parsed.price == 0.10
