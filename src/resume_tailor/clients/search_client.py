"""Tavily search wrapper with async support."""

from __future__ import annotations

import logging
import os

from tavily import AsyncTavilyClient

logger = logging.getLogger(__name__)


class SearchClient:
    """Async Tavily search client."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise ValueError(
                "Tavily API key required. Set TAVILY_API_KEY env var or pass api_key."
            )
        self.client = AsyncTavilyClient(api_key=key)
        self._search_count: int = 0

    async def search(
        self,
        query: str,
        max_results: int = 3,
        search_depth: str = "advanced",
    ) -> list[dict]:
        """Search and return list of {title, url, content} dicts."""
        logger.info("Searching: %s", query)
        self._search_count += 1
        try:
            response = await self.client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
            )
        except Exception:
            logger.error("Search failed", exc_info=True)
            raise
        return [
            {"title": r["title"], "url": r["url"], "content": r["content"]}
            for r in response.get("results", [])
        ]

    def get_search_count(self) -> int:
        """Return accumulated search count and reset the counter."""
        count = self._search_count
        self._search_count = 0
        return count
