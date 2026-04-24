"""Whale orchestrator: poll Polymarket /trades, detect large orders.

Replicates the late-binding `set_trade_store()` pattern from
`IntelligenceOrchestrator` so the DI layer can wire the store after
`TradeStore.init()` completes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.clients.polymarket_trades import PolymarketTradesClient
from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.intelligence import WhaleTrade

if TYPE_CHECKING:
    from app.models.market import Market

logger = get_logger(__name__)


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO string or unix seconds/millis into a UTC datetime."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        value = float(raw)
        # Heuristic: > ~year 3000 epoch seconds ⇒ must be milliseconds.
        if value > 1e12:
            value = value / 1000.0
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        text = str(raw)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return None


def _to_float(raw: Any, default: float = 0.0) -> float:
    try:
        if raw is None:
            return default
        return float(raw)
    except (TypeError, ValueError):
        return default


def _normalize_side(raw: Any) -> str:
    side = str(raw or "").upper().strip()
    if side in {"BUY", "SELL"}:
        return side
    # Some feeds use 0/1, bid/ask
    if side in {"BID", "1"}:
        return "BUY"
    if side in {"ASK", "0"}:
        return "SELL"
    return side or "BUY"


class WhaleOrchestrator:
    """Polls Polymarket /trades for whale activity."""

    def __init__(
        self,
        *,
        trades_client: PolymarketTradesClient | None = None,
        market_service: Any = None,
        trade_store: Any = None,
    ) -> None:
        self._trades_client = trades_client or PolymarketTradesClient()
        self._market_service = market_service
        self._trade_store = trade_store
        self._last_tick: datetime | None = None
        self._recent_trades: list[WhaleTrade] = []

    @property
    def last_tick(self) -> datetime | None:
        return self._last_tick

    async def set_trade_store(self, store: Any) -> None:
        """Wire the TradeStore late (after `init()` in DI). No history load."""
        self._trade_store = store

    async def tick(self, markets: list[Market]) -> list[WhaleTrade]:
        """Fetch recent trades per market, filter whales, persist, return them."""
        now = datetime.now(tz=UTC)
        cfg = app_config.intelligence.whale
        threshold = float(cfg.threshold_usd)
        window_min = int(cfg.pre_resolution_window_minutes)

        detected: list[WhaleTrade] = []
        for market in markets:
            try:
                raw_trades = await self._trades_client.fetch_recent_trades(
                    market.id, limit=50
                )
            except Exception as exc:  # defensive: client should swallow but guard
                logger.warning(
                    "whale_fetch_failed", market_id=market.id, error=str(exc)
                )
                continue

            for raw in raw_trades:
                try:
                    trade = self._parse_trade(raw, market, now, window_min)
                except Exception as exc:
                    logger.warning(
                        "whale_parse_failed",
                        market_id=market.id,
                        error=str(exc),
                    )
                    continue
                if trade is None:
                    continue
                if trade.size_usd < threshold:
                    continue
                detected.append(trade)
                await self._persist(trade)

        # Keep a short in-memory rolling window (last 500 whales)
        self._recent_trades.extend(detected)
        if len(self._recent_trades) > 500:
            self._recent_trades = self._recent_trades[-500:]

        self._last_tick = now
        logger.info(
            "whale_tick",
            markets_scanned=len(markets),
            whales_detected=len(detected),
            threshold_usd=threshold,
        )
        return detected

    def _parse_trade(
        self,
        raw: dict[str, Any],
        market: Market,
        now: datetime,
        window_min: int,
    ) -> WhaleTrade | None:
        trade_id = str(raw.get("id") or raw.get("trade_id") or "")
        if not trade_id:
            # Synthesize a stable key so PK upsert still works.
            trade_id = (
                f"{market.id}:{raw.get('taker', '')}:{raw.get('timestamp', '')}"
            )
        ts = _parse_timestamp(raw.get("timestamp") or raw.get("created_at")) or now
        wallet = str(
            raw.get("taker")
            or raw.get("wallet_address")
            or raw.get("maker")
            or ""
        )
        side = _normalize_side(raw.get("side"))
        size_usd = _to_float(raw.get("size_usd") or raw.get("size"))
        price = _to_float(raw.get("price"))
        # Guard: if size looks like share count (not USD) and price is present,
        # derive USD notional. We keep `size` as already-USD if the source
        # documents it that way — defensive only when price>0 and size<threshold
        # but size*price>=threshold (shares reported instead of USD).
        if size_usd and price and size_usd < 1.0:
            size_usd = size_usd * price

        is_pre_resolution = False
        if market.end_date is not None:
            delta = market.end_date - ts
            if timedelta(0) <= delta <= timedelta(minutes=window_min):
                is_pre_resolution = True

        return WhaleTrade(
            id=trade_id,
            timestamp=ts,
            market_id=market.id,
            wallet_address=wallet,
            side=side,
            size_usd=size_usd,
            price=price,
            is_pre_resolution=is_pre_resolution,
            raw_json=json.dumps(raw, default=str),
        )

    async def _persist(self, trade: WhaleTrade) -> None:
        if self._trade_store is None:
            return
        try:
            await self._trade_store.save_whale_trade({
                "id": trade.id,
                "timestamp": trade.timestamp.timestamp(),
                "market_id": trade.market_id,
                "wallet_address": trade.wallet_address,
                "side": trade.side,
                "size_usd": trade.size_usd,
                "price": trade.price,
                "is_pre_resolution": 1 if trade.is_pre_resolution else 0,
                "raw_json": trade.raw_json,
                "wallet_total_pnl": trade.wallet_total_pnl,
                "wallet_weekly_pnl": trade.wallet_weekly_pnl,
                "wallet_volume_rank": trade.wallet_volume_rank,
            })
        except Exception as exc:
            logger.warning(
                "whale_persist_failed",
                trade_id=trade.id,
                error=str(exc),
            )

    async def get_whale_activity(
        self, market_id: str, since_minutes: int = 360
    ) -> list[WhaleTrade]:
        """Load whale trades for a market from the store (since N minutes ago)."""
        if self._trade_store is None:
            return [t for t in self._recent_trades if t.market_id == market_id]
        cutoff = (
            datetime.now(tz=UTC) - timedelta(minutes=since_minutes)
        ).timestamp()
        try:
            rows = await self._trade_store.load_whale_trades(market_id, cutoff)
        except Exception as exc:
            logger.warning(
                "whale_activity_load_failed",
                market_id=market_id,
                error=str(exc),
            )
            return []
        result: list[WhaleTrade] = []
        for row in rows:
            try:
                ts_val = row.get("timestamp")
                if isinstance(ts_val, int | float):
                    ts = datetime.fromtimestamp(float(ts_val), tz=UTC)
                else:
                    parsed = _parse_timestamp(ts_val)
                    ts = parsed or datetime.now(tz=UTC)
                result.append(
                    WhaleTrade(
                        id=str(row["id"]),
                        timestamp=ts,
                        market_id=str(row["market_id"]),
                        wallet_address=str(row.get("wallet_address", "")),
                        side=str(row.get("side", "BUY")),
                        size_usd=float(row.get("size_usd", 0.0) or 0.0),
                        price=float(row.get("price", 0.0) or 0.0),
                        is_pre_resolution=bool(
                            int(row.get("is_pre_resolution", 0) or 0)
                        ),
                        raw_json=str(row.get("raw_json", "") or ""),
                        wallet_total_pnl=row.get("wallet_total_pnl"),
                        wallet_weekly_pnl=row.get("wallet_weekly_pnl"),
                        wallet_volume_rank=row.get("wallet_volume_rank"),
                    )
                )
            except Exception as exc:
                logger.warning("whale_row_parse_failed", error=str(exc))
        return result
