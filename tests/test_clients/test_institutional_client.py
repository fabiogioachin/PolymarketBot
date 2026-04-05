"""Tests for institutional source client."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.institutional_client import _FEDERAL_REGISTER_URL, InstitutionalClient
from app.models.intelligence import TimeHorizon

SAMPLE_FED_REGISTER = {
    "count": 2,
    "results": [
        {
            "title": "Regulation on Import Tariffs",
            "html_url": "https://www.federalregister.gov/documents/2026/04/04/1",
            "publication_date": "2026-04-04",
            "abstract": "New tariff rules for semiconductor imports.",
            "agencies": ["Commerce Department"],
        },
        {
            "title": "Environmental Protection Update",
            "html_url": "https://www.federalregister.gov/documents/2026/04/03/2",
            "publication_date": "2026-04-03",
            "abstract": None,
            "agencies": ["EPA"],
        },
    ],
}


@pytest.fixture()
def inst_client() -> InstitutionalClient:
    return InstitutionalClient()


class TestFetchFederalRegister:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_news_items(self, inst_client: InstitutionalClient) -> None:
        respx.get(_FEDERAL_REGISTER_URL).mock(
            return_value=httpx.Response(200, json=SAMPLE_FED_REGISTER)
        )

        items = await inst_client.fetch_federal_register()
        await inst_client.close()

        assert len(items) == 2
        assert items[0].title == "Regulation on Import Tariffs"
        assert items[0].source == "institutional:federal_register"
        assert items[0].domain == "economics"
        assert items[0].time_horizon == TimeHorizon.MEDIUM

    @respx.mock
    @pytest.mark.asyncio()
    async def test_failure_returns_empty(self, inst_client: InstitutionalClient) -> None:
        respx.get(_FEDERAL_REGISTER_URL).mock(return_value=httpx.Response(503))

        items = await inst_client.fetch_federal_register()
        await inst_client.close()

        assert items == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_field_mapping(self, inst_client: InstitutionalClient) -> None:
        respx.get(_FEDERAL_REGISTER_URL).mock(
            return_value=httpx.Response(200, json=SAMPLE_FED_REGISTER)
        )

        items = await inst_client.fetch_federal_register()
        await inst_client.close()

        first = items[0]
        assert first.url == "https://www.federalregister.gov/documents/2026/04/04/1"
        assert first.published is not None
        assert first.published.year == 2026
        assert first.summary == "New tariff rules for semiconductor imports."
        assert first.tags == ["Commerce Department"]

        # Second item has None abstract -> empty summary
        second = items[1]
        assert second.summary == ""
        assert second.tags == ["EPA"]


class TestFetchAll:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_delegates_to_federal_register(
        self, inst_client: InstitutionalClient
    ) -> None:
        respx.get(_FEDERAL_REGISTER_URL).mock(
            return_value=httpx.Response(200, json=SAMPLE_FED_REGISTER)
        )

        items = await inst_client.fetch_all()
        await inst_client.close()

        assert len(items) == 2
