"""Snapshot writer: periodically writes static/dss/intelligence_snapshot.json.

The file is the data contract between the Python backend and the standalone
DSS HTML artifact (``static/dss/dss.html``).  It is written atomically via a
temporary file + ``os.replace`` so readers never observe a partial JSON file —
this is safe on Windows (same filesystem, no EXDEV rename issue).

Cadence: every 5 minutes.  A ``tick()`` call is a no-op if fewer than 5
minutes have elapsed since the last successful write (deduplication guard).

Wiring: use :func:`~app.core.dependencies.get_snapshot_writer` to get the
singleton.  Wire dependencies with the ``set_*`` methods (late-binding pattern
mirroring :class:`~app.services.intelligence_orchestrator.IntelligenceOrchestrator`).
The orchestrator will call ``tick()`` from ``ExecutionEngine.tick()`` after S4b
is merged.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.dss_snapshot import DSSSnapshot, DSSSnapshotMarket, DSSSnapshotWhale

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_DEFAULT_OUTPUT = Path("static/dss/intelligence_snapshot.json")
_TICK_INTERVAL = timedelta(minutes=5)


class SnapshotWriter:
    """Writes ``intelligence_snapshot.json`` on a 5-minute cadence.

    All dependencies are optional and injected after construction via the
    ``set_*`` methods.  Missing dependencies produce empty/default sections
    in the snapshot rather than failures.
    """

    def __init__(
        self,
        output_path: Path = _DEFAULT_OUTPUT,
    ) -> None:
        self._output_path = output_path
        self._engine: Any = None
        self._whale_orch: Any = None
        self._popular_orch: Any = None
        self._leaderboard_orch: Any = None
        self._trade_store: Any = None
        self._last_tick: datetime | None = None

    # ── Late-binding setters ─────────────────────────────────────────────

    def set_engine(self, engine: Any) -> None:
        """Wire the ExecutionEngine (for valuations + positions + risk state)."""
        self._engine = engine

    def set_whale_orchestrator(self, orch: Any) -> None:
        """Wire the WhaleOrchestrator (for recent whale activity)."""
        self._whale_orch = orch

    def set_popular_markets_orchestrator(self, orch: Any) -> None:
        """Wire the PopularMarketsOrchestrator (for popular_markets_top20)."""
        self._popular_orch = orch

    def set_leaderboard_orchestrator(self, orch: Any) -> None:
        """Wire the LeaderboardOrchestrator (for leaderboard_top50)."""
        self._leaderboard_orch = orch

    def set_trade_store(self, store: Any) -> None:
        """Wire the TradeStore (for whale/insider queries by time window)."""
        self._trade_store = store

    # ── Public API ───────────────────────────────────────────────────────

    async def tick(self) -> None:
        """Build and atomically write the DSS snapshot.

        Skips the write if fewer than 5 minutes have elapsed since the last
        successful tick (deduplication / rate-limiting guard).
        """
        now = datetime.now(tz=UTC)
        if self._last_tick is not None and (now - self._last_tick) < _TICK_INTERVAL:
            logger.debug(
                "snapshot_tick_skipped",
                elapsed_seconds=(now - self._last_tick).total_seconds(),
            )
            return

        try:
            snapshot = await self._build_snapshot(now)
            self._write_atomic(snapshot)
            self._last_tick = now
            logger.info(
                "snapshot_written",
                path=str(self._output_path),
                markets=len(snapshot.monitored_markets),
                whales=len(snapshot.recent_whales),
            )
        except Exception as exc:
            logger.error("snapshot_write_failed", error=str(exc))
            # Do NOT update _last_tick — allow retry on next call.

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _build_snapshot(self, now: datetime) -> DSSSnapshot:
        """Assemble a DSSSnapshot from all wired dependencies."""
        cfg = app_config
        weights = {
            k: float(v)
            for k, v in cfg.valuation.weights.model_dump().items()
        }
        vol_cfg = cfg.valuation.volatility
        volatility_config = {
            "k_short": vol_cfg.k_short,
            "k_medium": vol_cfg.k_medium,
            "k_long": vol_cfg.k_long,
            "velocity_alpha": vol_cfg.velocity_alpha,
            "strong_edge_threshold": vol_cfg.strong_edge_threshold,
            "window_minutes": float(vol_cfg.window_minutes),
        }

        config_version = f"{cfg.app.name}:{cfg.app.version}"

        # --- Monitored markets ---
        monitored_markets = await self._build_monitored_markets()

        # --- Open positions ---
        open_positions = await self._build_open_positions()

        # Mark which market_ids have open positions
        open_market_ids = {p.get("market_id", "") for p in open_positions}
        for m in monitored_markets:
            if m.market_id in open_market_ids:
                m.has_open_position = True

        # --- Whale / insider activity (6h window for whales, 24h for insiders) ---
        recent_whales = await self._build_whale_list(now, hours=6, pre_resolution_only=False)
        recent_insiders = await self._build_whale_list(now, hours=24, pre_resolution_only=True)

        # --- Popular markets ---
        popular_markets_top20 = self._build_popular_markets()

        # --- Leaderboard ---
        leaderboard_top50 = self._build_leaderboard()

        # --- Risk state ---
        risk_state = self._build_risk_state()

        return DSSSnapshot(
            generated_at=now,
            config_version=config_version,
            weights=weights,
            volatility_config=volatility_config,
            monitored_markets=monitored_markets[:50],
            recent_whales=recent_whales[:50],
            recent_insiders=recent_insiders[:50],
            popular_markets_top20=popular_markets_top20[:20],
            leaderboard_top50=leaderboard_top50[:50],
            open_positions=open_positions,
            risk_state=risk_state,
        )

    async def _build_monitored_markets(self) -> list[DSSSnapshotMarket]:
        """Extract market entries from the engine's last valuations.

        Falls back to an empty list if the engine is not yet wired or has no
        valuations cached.
        """
        if self._engine is None:
            return []

        # Try to access the last valuations produced by assess_batch.
        # ExecutionEngine stores them in the ``_last_valuations`` attribute
        # (populated after tick).  We do a defensive getattr — if S4b has not
        # yet been merged the attribute won't exist.
        valuations: dict[str, Any] = getattr(self._engine, "_last_valuations", {})

        result: list[DSSSnapshotMarket] = []
        for market_id, val in valuations.items():
            # val is a ValuationResult
            question = ""
            # Try to get the question from the market_service cache
            ms = getattr(self._engine, "_market_service", None)
            if ms is not None:
                market_cache: dict[str, Any] = getattr(ms, "_cache", {})
                m = market_cache.get(market_id)
                if m is not None:
                    question = getattr(m, "question", "")

            result.append(
                DSSSnapshotMarket(
                    market_id=market_id,
                    question=question,
                    market_price=float(getattr(val, "market_price", 0.0)),
                    fair_value=_opt_float(getattr(val, "fair_value", None)),
                    edge_central=_opt_float(getattr(val, "fee_adjusted_edge", None)),
                    edge_lower=_opt_float(getattr(val, "edge_lower", None)),
                    edge_dynamic=_opt_float(getattr(val, "edge_dynamic", None)),
                    realized_volatility=_opt_float(
                        getattr(val, "realized_volatility", None)
                    ),
                    has_open_position=False,  # back-filled below
                    recommendation=str(getattr(val, "recommendation", "HOLD")),
                )
            )

        # Sort by |edge_dynamic| descending (most interesting first for DSS)
        result.sort(
            key=lambda m: abs(m.edge_dynamic or m.edge_central or 0.0), reverse=True
        )
        return result

    async def _build_open_positions(self) -> list[dict]:  # type: ignore[type-arg]
        """Return open positions from the executor, or empty list."""
        if self._engine is None:
            return []
        executor = getattr(self._engine, "_executor", None)
        if executor is None:
            return []
        try:
            positions = await executor.get_positions()
        except Exception as exc:
            logger.warning("snapshot_positions_fetch_failed", error=str(exc))
            return []

        result = []
        for pos in positions:
            result.append({
                "token_id": str(getattr(pos, "token_id", "")),
                "market_id": str(getattr(pos, "market_id", "")),
                "side": str(getattr(pos, "side", "")),
                "size": float(getattr(pos, "size", 0.0)),
                "avg_price": float(getattr(pos, "avg_price", 0.0)),
                "current_price": float(getattr(pos, "current_price", 0.0)),
            })
        return result

    async def _build_whale_list(
        self,
        now: datetime,
        hours: int,
        pre_resolution_only: bool,
    ) -> list[DSSSnapshotWhale]:
        """Load recent whale trades from the trade store.

        Loads from ``trade_store`` if available, otherwise falls back to the
        whale orchestrator's in-memory cache.
        """
        if self._trade_store is not None:
            return await self._build_whale_from_store(now, hours, pre_resolution_only)
        if self._whale_orch is not None:
            return self._build_whale_from_memory(now, hours, pre_resolution_only)
        return []

    async def _build_whale_from_store(
        self,
        now: datetime,
        hours: int,
        pre_resolution_only: bool,
    ) -> list[DSSSnapshotWhale]:
        """Query trade_store for whale trades across all markets."""
        cutoff_ts = (now - timedelta(hours=hours)).timestamp()
        result: list[DSSSnapshotWhale] = []
        try:
            # load_whale_trades requires a market_id; we use a broad query via
            # the SQL store directly. Fall back to orchestrator memory if the
            # store doesn't have a global query method.
            conn = getattr(self._trade_store, "_conn", None)
            if conn is None:
                return []
            cursor = await conn.execute(
                """SELECT timestamp, market_id, wallet_address, side,
                          size_usd, is_pre_resolution, wallet_total_pnl
                   FROM whale_trades
                   WHERE timestamp >= ?
                   ORDER BY timestamp DESC
                   LIMIT 200""",
                (cutoff_ts,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                is_pre = bool(int(row["is_pre_resolution"] or 0))
                if pre_resolution_only and not is_pre:
                    continue
                ts_raw = row["timestamp"]
                ts = (
                    datetime.fromtimestamp(float(ts_raw), tz=UTC)
                    if isinstance(ts_raw, int | float)
                    else now
                )
                result.append(
                    DSSSnapshotWhale(
                        timestamp=ts,
                        market_id=str(row["market_id"]),
                        wallet_address=str(row["wallet_address"] or ""),
                        side=str(row["side"] or ""),
                        size_usd=float(row["size_usd"] or 0.0),
                        is_pre_resolution=is_pre,
                        wallet_total_pnl=(
                            float(row["wallet_total_pnl"])
                            if row["wallet_total_pnl"] is not None
                            else None
                        ),
                    )
                )
        except Exception as exc:
            logger.warning("snapshot_whale_store_failed", error=str(exc))
        return result

    def _build_whale_from_memory(
        self,
        now: datetime,
        hours: int,
        pre_resolution_only: bool,
    ) -> list[DSSSnapshotWhale]:
        """Fall back to WhaleOrchestrator's in-memory rolling window."""
        recent: list[Any] = getattr(self._whale_orch, "_recent_trades", [])
        cutoff = now - timedelta(hours=hours)
        result: list[DSSSnapshotWhale] = []
        for trade in recent:
            ts = getattr(trade, "timestamp", None)
            if ts is None or ts < cutoff:
                continue
            is_pre = bool(getattr(trade, "is_pre_resolution", False))
            if pre_resolution_only and not is_pre:
                continue
            result.append(
                DSSSnapshotWhale(
                    timestamp=ts,
                    market_id=str(getattr(trade, "market_id", "")),
                    wallet_address=str(getattr(trade, "wallet_address", "")),
                    side=str(getattr(trade, "side", "")),
                    size_usd=float(getattr(trade, "size_usd", 0.0)),
                    is_pre_resolution=is_pre,
                    wallet_total_pnl=getattr(trade, "wallet_total_pnl", None),
                )
            )
        result.sort(key=lambda w: w.timestamp, reverse=True)
        return result

    def _build_popular_markets(self) -> list[dict]:  # type: ignore[type-arg]
        """Return the latest popular-markets snapshot."""
        if self._popular_orch is None:
            return []
        markets: list[Any] = getattr(self._popular_orch, "get_popular_markets", lambda: [])()
        result: list[dict[str, Any]] = []
        for pm in markets:
            result.append({
                "market_id": str(getattr(pm, "market_id", "")),
                "question": str(getattr(pm, "question", "")),
                "volume24h": float(getattr(pm, "volume24h", 0.0)),
                "liquidity": _opt_float(getattr(pm, "liquidity", None)),
            })
        return result

    def _build_leaderboard(self) -> list[dict]:  # type: ignore[type-arg]
        """Return the latest leaderboard snapshot."""
        if self._leaderboard_orch is None:
            return []
        entries: list[Any] = getattr(
            self._leaderboard_orch, "get_leaderboard", lambda: []
        )()
        result: list[dict[str, Any]] = []
        for entry in entries:
            result.append({
                "rank": int(getattr(entry, "rank", 0)),
                "wallet_address": str(getattr(entry, "wallet_address", "")),
                "pnl_usd": float(getattr(entry, "pnl_usd", 0.0)),
                "win_rate": _opt_float(getattr(entry, "win_rate", None)),
                "timeframe": str(getattr(entry, "timeframe", "")),
            })
        return result

    def _build_risk_state(self) -> dict:  # type: ignore[type-arg]
        """Extract key risk metrics from the engine's risk manager."""
        if self._engine is None:
            return {"exposure_pct": 0.0, "circuit_breaker_open": False, "daily_pnl": 0.0}
        risk_mgr = getattr(self._engine, "_risk", None)
        cb = getattr(self._engine, "_circuit_breaker", None)
        capital = 150.0  # default; matches dependencies.py wiring

        exposure = 0.0
        daily_pnl = 0.0
        cb_open = False

        if risk_mgr is not None:
            try:
                exposure = float(getattr(risk_mgr, "current_exposure", 0.0))
                daily_pnl = float(getattr(risk_mgr, "daily_pnl", 0.0))
            except Exception as exc:  # defensive: risk state must not crash snapshot
                logger.debug("snapshot_risk_state_failed", error=str(exc))

        if cb is not None:
            try:
                state = cb.check()
                cb_open = bool(getattr(state, "is_tripped", False))
            except Exception as exc:  # defensive: cb state must not crash snapshot
                logger.debug("snapshot_cb_state_failed", error=str(exc))

        exposure_pct = (exposure / capital * 100.0) if capital > 0 else 0.0

        return {
            "exposure_pct": round(exposure_pct, 2),
            "circuit_breaker_open": cb_open,
            "daily_pnl": round(daily_pnl, 4),
        }

    def _write_atomic(self, snapshot: DSSSnapshot) -> None:
        """Serialize snapshot to JSON and write atomically.

        Uses a temporary file + ``os.replace`` which is atomic on Windows when
        both paths are on the same filesystem (no cross-device rename).
        """
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._output_path.with_suffix(self._output_path.suffix + ".tmp")
        payload = snapshot.model_dump_json(indent=None)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self._output_path)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _opt_float(value: Any) -> float | None:
    """Convert a value to float, returning None if it's None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
