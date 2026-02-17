"""Tests for SearchClient (Tavily search wrapper)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestSearchClientInit:
    def test_missing_api_key_raises_value_error(self, monkeypatch):
        """Raises ValueError when no api_key arg and TAVILY_API_KEY env var is absent."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient"):
            from resume_tailor.clients.search_client import SearchClient
            with pytest.raises(ValueError, match="Tavily API key required"):
                SearchClient()

    def test_init_with_api_key_succeeds(self):
        """No error raised when api_key is passed directly."""
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient"):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient(api_key="test-key")
            assert client is not None

    def test_init_with_env_var_succeeds(self, monkeypatch):
        """No error raised when TAVILY_API_KEY env var is set."""
        monkeypatch.setenv("TAVILY_API_KEY", "env-key")
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient"):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient()
            assert client is not None


class TestSearchClientSearch:
    async def test_search_returns_formatted_results(self, monkeypatch):
        """search() returns list of {title, url, content} dicts from the API response."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_tavily = AsyncMock()
        mock_tavily.search = AsyncMock(return_value={
            "results": [
                {"title": "Result Title", "url": "https://example.com", "content": "Some content"},
            ]
        })
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient", return_value=mock_tavily):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient(api_key="test-key")
            results = await client.search("test query")

        assert len(results) == 1
        assert results[0] == {
            "title": "Result Title",
            "url": "https://example.com",
            "content": "Some content",
        }

    async def test_search_count_increments_with_each_call(self, monkeypatch):
        """_search_count increases by 1 for every search() call made."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_tavily = AsyncMock()
        mock_tavily.search = AsyncMock(return_value={"results": []})
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient", return_value=mock_tavily):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient(api_key="test-key")
            await client.search("query one")
            await client.search("query two")

        assert client._search_count == 2

    async def test_search_count_resets_after_get_search_count(self, monkeypatch):
        """get_search_count() returns the accumulated count and resets it to zero."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_tavily = AsyncMock()
        mock_tavily.search = AsyncMock(return_value={"results": []})
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient", return_value=mock_tavily):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient(api_key="test-key")
            await client.search("query")

        first_count = client.get_search_count()
        second_count = client.get_search_count()

        assert first_count == 1
        assert second_count == 0

    async def test_search_returns_empty_list_when_no_results(self, monkeypatch):
        """search() returns an empty list when API response contains no results."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_tavily = AsyncMock()
        mock_tavily.search = AsyncMock(return_value={"results": []})
        with patch("resume_tailor.clients.search_client.AsyncTavilyClient", return_value=mock_tavily):
            from resume_tailor.clients.search_client import SearchClient
            client = SearchClient(api_key="test-key")
            results = await client.search("empty query")

        assert results == []
