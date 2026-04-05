"""Tests for GDELT monitoring service."""

from __future__ import annotations

from datetime import UTC

import httpx
import pytest
import respx

from app.clients.gdelt_client import GdeltClient
from app.services.gdelt_service import GdeltService, _parse_gdelt_date

DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


def _make_service() -> tuple[GdeltService, GdeltClient]:
    """Create a service with a test client (small backoff)."""
    client = GdeltClient(rate_limit=5, max_retries=1, backoff=0.01)
    service = GdeltService(client=client)
    return service, client


def _mock_no_anomaly() -> None:
    """Mock GDELT responses that produce no anomaly."""
    respx.get(DOC_BASE).mock(
        return_value=httpx.Response(200, json={"articles": [], "timeline": []})
    )


def _mock_volume_timeline(values: list[int]) -> dict:
    return {
        "timeline": [
            {"series": [{"date": f"2026-04-0{i+1}", "value": v} for i, v in enumerate(values)]}
        ]
    }


def _mock_tone_timeline(values: list[float]) -> dict:
    return {
        "timeline": [
            {"series": [{"date": f"2026-04-0{i+1}", "value": v} for i, v in enumerate(values)]}
        ]
    }


# ── Build queries ─────────────────────────────────────────────────────


class TestBuildQueries:
    def test_builds_from_watchlist(self) -> None:
        service, _ = _make_service()
        queries = service._build_queries()
        # Should include themes + actors + countries from default config
        assert "ELECTION" in queries
        assert "USA" in queries
        assert "US" in queries
        assert len(queries) == 14  # 5 themes + 4 actors + 5 countries


# ── Poll watchlist ────────────────────────────────────────────────────


class TestPollWatchlist:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_anomaly_returns_empty(self) -> None:
        """When volume and tone are normal, no events are returned."""
        service, client = _make_service()

        # Set baselines so volume ratio < 2 and tone shift < 1.5
        for q in service._build_queries():
            service._baselines[q] = {"volume": 100, "tone": 0.0}

        # Mock: distinguish by mode param so volume and tone return correct values
        def side_effect(request: httpx.Request) -> httpx.Response:
            mode = request.url.params.get("mode", "")
            if mode == "artlist":
                return httpx.Response(200, json={"articles": []})
            if mode == "timelinevol":
                return httpx.Response(
                    200, json=_mock_volume_timeline([100, 100, 100])
                )
            if mode == "timelinetone":
                # Tone close to baseline (0.0), shift < 1.5
                return httpx.Response(
                    200, json=_mock_tone_timeline([0.0, 0.2, 0.5])
                )
            return httpx.Response(200, json={})

        respx.get(DOC_BASE).mock(side_effect=side_effect)

        events = await service.poll_watchlist()
        await client.close()

        assert events == []
        assert service._last_poll is not None

    @respx.mock
    @pytest.mark.asyncio()
    async def test_volume_spike_detected(self) -> None:
        """Volume 3x baseline triggers a volume_spike event."""
        service, client = _make_service()
        service._baselines["ELECTION"] = {"volume": 100, "tone": 0.0}

        # Only test one query to simplify mocking
        service._watchlist = {"themes": ["ELECTION"], "actors": [], "countries": []}

        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            mode = request.url.params.get("mode", "")
            if mode == "artlist":
                return httpx.Response(
                    200,
                    json={
                        "articles": [
                            {
                                "url": "https://reuters.com/spike",
                                "title": "Election Spike",
                                "seendate": "20260404T120000Z",
                                "domain": "reuters.com",
                                "sourcecountry": "United States",
                                "language": "English",
                            }
                        ]
                    },
                )
            if mode == "timelinevol":
                return httpx.Response(
                    200, json=_mock_volume_timeline([100, 120, 300])
                )
            if mode == "timelinetone":
                return httpx.Response(
                    200, json=_mock_tone_timeline([0.0, 0.2, 0.5])
                )
            return httpx.Response(200, json={})

        respx.get(DOC_BASE).mock(side_effect=side_effect)

        events = await service.poll_watchlist()
        await client.close()

        assert len(events) == 1
        assert events[0].event_type == "volume_spike"
        assert events[0].query == "ELECTION"
        assert events[0].volume_ratio >= 2.0
        assert len(events[0].articles) == 1

    @respx.mock
    @pytest.mark.asyncio()
    async def test_tone_shift_detected(self) -> None:
        """Tone shift > 1.5 triggers a tone_shift event."""
        service, client = _make_service()
        service._baselines["ECON_INFLATION"] = {"volume": 100, "tone": 0.0}
        service._watchlist = {
            "themes": ["ECON_INFLATION"],
            "actors": [],
            "countries": [],
        }

        def side_effect(request: httpx.Request) -> httpx.Response:
            mode = request.url.params.get("mode", "")
            if mode == "artlist":
                return httpx.Response(200, json={"articles": []})
            if mode == "timelinevol":
                # Volume normal (ratio ~1.0)
                return httpx.Response(
                    200, json=_mock_volume_timeline([100, 100, 100])
                )
            if mode == "timelinetone":
                # Tone shifted to -3.0 (shift=3.0 > threshold)
                return httpx.Response(
                    200, json=_mock_tone_timeline([0.0, -1.0, -3.0])
                )
            return httpx.Response(200, json={})

        respx.get(DOC_BASE).mock(side_effect=side_effect)

        events = await service.poll_watchlist()
        await client.close()

        assert len(events) == 1
        assert events[0].event_type == "tone_shift"
        assert events[0].tone.is_anomaly is True
        assert abs(events[0].tone.shift) >= 1.5


# ── Check topic ───────────────────────────────────────────────────────


class TestCheckTopic:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_ad_hoc_check(self) -> None:
        service, client = _make_service()
        service._baselines["CUSTOM_TOPIC"] = {"volume": 50, "tone": 1.0}

        def side_effect(request: httpx.Request) -> httpx.Response:
            mode = request.url.params.get("mode", "")
            if mode == "artlist":
                return httpx.Response(
                    200,
                    json={
                        "articles": [
                            {"url": "https://example.com", "title": "Custom"}
                        ]
                    },
                )
            if mode == "timelinevol":
                return httpx.Response(200, json=_mock_volume_timeline([50, 60, 200]))
            if mode == "timelinetone":
                return httpx.Response(200, json=_mock_tone_timeline([1.0, 1.0, 1.0]))
            return httpx.Response(200, json={})

        respx.get(DOC_BASE).mock(side_effect=side_effect)

        event = await service.check_topic("CUSTOM_TOPIC")
        await client.close()

        assert event is not None
        assert event.query == "CUSTOM_TOPIC"
        assert event.volume_ratio >= 2.0


# ── Update baselines ──────────────────────────────────────────────────


class TestUpdateBaselines:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_computes_averages(self) -> None:
        service, client = _make_service()
        service._watchlist = {"themes": ["TEST_THEME"], "actors": [], "countries": []}

        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            mode = request.url.params.get("mode", "")
            if mode == "timelinevol":
                return httpx.Response(
                    200, json=_mock_volume_timeline([100, 200, 300])
                )
            if mode == "timelinetone":
                return httpx.Response(
                    200, json=_mock_tone_timeline([1.0, 2.0, 3.0])
                )
            return httpx.Response(200, json={})

        respx.get(DOC_BASE).mock(side_effect=side_effect)

        await service.update_baselines()
        await client.close()

        assert "TEST_THEME" in service._baselines
        assert service._baselines["TEST_THEME"]["volume"] == pytest.approx(200.0)
        assert service._baselines["TEST_THEME"]["tone"] == pytest.approx(2.0)


# ── Parse GDELT date ─────────────────────────────────────────────────


class TestParseGdeltDate:
    def test_valid_date(self) -> None:
        result = _parse_gdelt_date("20260404T120000Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 4
        assert result.hour == 12
        assert result.tzinfo == UTC

    def test_empty_string(self) -> None:
        assert _parse_gdelt_date("") is None

    def test_invalid_format(self) -> None:
        assert _parse_gdelt_date("not-a-date") is None

    def test_partial_date(self) -> None:
        assert _parse_gdelt_date("20260404") is None
