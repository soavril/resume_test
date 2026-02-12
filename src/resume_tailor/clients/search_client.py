"""Tavily search wrapper with async support."""

from __future__ import annotations

import os

from tavily import AsyncTavilyClient


class SearchClient:
    """Async Tavily search client."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise ValueError(
                "Tavily API key required. Set TAVILY_API_KEY env var or pass api_key."
            )
        self.client = AsyncTavilyClient(api_key=key)

    async def search(
        self,
        query: str,
        max_results: int = 3,
        search_depth: str = "advanced",
    ) -> list[dict]:
        """Search and return list of {title, url, content} dicts."""
        response = await self.client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
        )
        return [
            {"title": r["title"], "url": r["url"], "content": r["content"]}
            for r in response.get("results", [])
        ]
