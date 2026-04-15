"""Tests for GDELT async client."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.gdelt_client import GdeltClient

DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
GEO_BASE = "https://api.gdeltproject.org/api/v2/geo/geo"


@pytest.fixture()
def client() -> GdeltClient:
    c = GdeltClient(rate_limit=5, max_retries=2, backoff=0.01)
    return c


# ── Default configuration ─────────────────────────────────────────────


class TestDefaults:
    def test_default_max_retries(self) -> None:
        c = GdeltClient()
        assert c._max_retries == 1

    def test_default_backoff(self) -> None:
        c = GdeltClient()
        assert c._backoff == 5.0


# ── Article search ────────────────────────────────────────────────────


class TestArticleSearch:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_articles(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(
                200,
                json={
                    "articles": [
                        {
                            "url": "https://reuters.com/article1",
                            "title": "Test Article",
                            "seendate": "20260404T120000Z",
                            "domain": "reuters.com",
                            "sourcecountry": "United States",
                            "language": "English",
                        },
                        {
                            "url": "https://bbc.com/article2",
                            "title": "Another Article",
                            "seendate": "20260404T130000Z",
                            "domain": "bbc.com",
                            "sourcecountry": "United Kingdom",
                            "language": "English",
                        },
                    ]
                },
            )
        )
        articles = await client.article_search("ELECTION")
        await client.close()

        assert len(articles) == 2
        assert articles[0]["title"] == "Test Article"
        assert articles[1]["domain"] == "bbc.com"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_response(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(200, json={"articles": []})
        )
        articles = await client.article_search("NONEXISTENT_TOPIC")
        await client.close()
        assert articles == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_articles_key(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(200, json={})
        )
        articles = await client.article_search("EMPTY")
        await client.close()
        assert articles == []


# ── Timeline volume ───────────────────────────────────────────────────


class TestTimelineVolume:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_series_data(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(
                200,
                json={
                    "timeline": [
                        {
                            "series": [
                                {"date": "2026-04-01", "value": 100},
                                {"date": "2026-04-02", "value": 150},
                                {"date": "2026-04-03", "value": 120},
                            ]
                        }
                    ]
                },
            )
        )
        series = await client.timeline_volume("ELECTION")
        await client.close()

        assert len(series) == 3
        assert series[0]["value"] == 100
        assert series[-1]["value"] == 120

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_timeline(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(200, json={"timeline": []})
        )
        series = await client.timeline_volume("NOTHING")
        await client.close()
        assert series == []


# ── Timeline tone ─────────────────────────────────────────────────────


class TestTimelineTone:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_tone_series(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(
                200,
                json={
                    "timeline": [
                        {
                            "series": [
                                {"date": "2026-04-01", "value": 1.2},
                                {"date": "2026-04-02", "value": -0.5},
                                {"date": "2026-04-03", "value": 2.3},
                            ]
                        }
                    ]
                },
            )
        )
        series = await client.timeline_tone("ECON_INFLATION")
        await client.close()

        assert len(series) == 3
        assert series[1]["value"] == -0.5


# ── Geo query ─────────────────────────────────────────────────────────


class TestGeoQuery:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_features(self, client: GdeltClient) -> None:
        respx.get(GEO_BASE).mock(
            return_value=httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                            "properties": {"name": "Washington DC"},
                        }
                    ],
                },
            )
        )
        features = await client.geo_query("USA")
        await client.close()

        assert len(features) == 1
        assert features[0]["properties"]["name"] == "Washington DC"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_features(self, client: GdeltClient) -> None:
        respx.get(GEO_BASE).mock(
            return_value=httpx.Response(200, json={"features": []})
        )
        features = await client.geo_query("NOWHERE")
        await client.close()
        assert features == []


# ── Retry behavior ────────────────────────────────────────────────────


class TestRetryBehavior:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_429(self, client: GdeltClient) -> None:
        route = respx.get(DOC_BASE)
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(
                200,
                json={"articles": [{"url": "https://test.com", "title": "OK"}]},
            ),
        ]
        articles = await client.article_search("RETRY_TEST")
        await client.close()

        assert len(articles) == 1
        assert route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_500(self, client: GdeltClient) -> None:
        route = respx.get(DOC_BASE)
        route.side_effect = [
            httpx.Response(500, text="server error"),
            httpx.Response(500, text="server error"),
            httpx.Response(
                200,
                json={"articles": [{"url": "https://test.com", "title": "Recovered"}]},
            ),
        ]
        articles = await client.article_search("SERVER_ERR")
        await client.close()

        assert len(articles) == 1
        assert articles[0]["title"] == "Recovered"
        assert route.call_count == 3

    @respx.mock
    @pytest.mark.asyncio()
    async def test_raises_after_exhausted_retries(self, client: GdeltClient) -> None:
        respx.get(DOC_BASE).mock(
            return_value=httpx.Response(500, text="always fails")
        )
        with pytest.raises(RuntimeError, match="All .* attempts failed"):
            await client.article_search("ALWAYS_FAIL")
        await client.close()
