"""Client for institutional sources: Federal Register, EU Official Journal, etc."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger
from app.models.intelligence import NewsItem, TimeHorizon

logger = get_logger(__name__)

_FEDERAL_REGISTER_URL = "https://www.federalregister.gov/api/v1/documents.json"


class InstitutionalClient:
    """Fetches data from institutional / government sources."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PolymarketBot/0.1",
                },
            )
        return self._client

    async def fetch_federal_register(self, *, per_page: int = 20) -> list[NewsItem]:
        """Fetch recent Federal Register documents."""
        try:
            resp = await self._get_client().get(
                _FEDERAL_REGISTER_URL,
                params={"per_page": per_page, "order": "newest"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("federal_register_fetch_failed", error=str(exc))
            return []

        items: list[NewsItem] = []
        for doc in data.get("results", []):
            published = self._parse_date(doc.get("publication_date"))
            agencies_raw = doc.get("agencies") or []
            tags: list[str] = [
                a.get("raw_name", "") if isinstance(a, dict) else str(a)
                for a in agencies_raw
                if a
            ]

            items.append(
                NewsItem(
                    source="institutional:federal_register",
                    title=doc.get("title", ""),
                    url=doc.get("html_url", ""),
                    published=published,
                    domain="economics",
                    time_horizon=TimeHorizon.MEDIUM,
                    summary=(doc.get("abstract") or "")[:500],
                    tags=tags,
                )
            )

        logger.info("federal_register_fetched", items=len(items))
        return items

    async def fetch_all(self) -> list[NewsItem]:
        """Fetch from all institutional sources."""
        return await self.fetch_federal_register()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None


institutional_client = InstitutionalClient()
