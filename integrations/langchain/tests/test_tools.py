"""Tests for AlterLabScrapeTool."""

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_alterlab.tools import AlterLabScrapeTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE: Dict[str, Any] = {
    "url": "https://example.com/article",
    "status_code": 200,
    "content": {
        "markdown": "# Example Article\n\nThis is the article body.",
        "text": "Example Article. This is the article body.",
    },
    "title": "Example Article",
    "author": "Jane Doe",
    "published_at": "2026-01-15T10:00:00Z",
    "metadata": {"language": "en"},
    "response_time_ms": 300,
    "billing": {
        "total_credits": 2,
        "tier_used": "2",
        "escalations": [],
        "savings": 0,
    },
    "extraction_method": "algorithmic",
}

EMPTY_RESPONSE: Dict[str, Any] = {
    "url": "https://example.com/empty",
    "status_code": 200,
    "content": {},
}


@pytest.fixture()
def mock_sync_client():
    """Create a mock AlterLabSync client."""
    client = MagicMock()
    client.scrape.return_value = SAMPLE_RESPONSE
    client.close = MagicMock()
    return client


@pytest.fixture()
def mock_async_client():
    """Create a mock AlterLab async client."""
    client = AsyncMock()
    client.scrape.return_value = SAMPLE_RESPONSE
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestToolInit:
    def test_init_with_env_key(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            assert tool.name == "alterlab_scrape"
            assert "scrape" in tool.description.lower()

    def test_init_with_explicit_key(self):
        tool = AlterLabScrapeTool(api_key="sk_live_xyz")
        assert tool.api_key == "sk_live_xyz"

    def test_init_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ALTERLAB_API_KEY", None)
            with pytest.raises(ValueError, match="API key is required"):
                AlterLabScrapeTool()

    def test_custom_params(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool(params={"formats": ["markdown"], "mode": "js"})
            assert tool.params == {"formats": ["markdown"], "mode": "js"}


# ---------------------------------------------------------------------------
# Sync execution tests
# ---------------------------------------------------------------------------


class TestSyncRun:
    def test_scrape_returns_content(self, mock_sync_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://example.com/article")

        assert "Example Article" in result
        assert "article body" in result
        mock_sync_client.scrape.assert_called_once_with("https://example.com/article")
        mock_sync_client.close.assert_called_once()

    def test_scrape_with_params(self, mock_sync_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool(params={"mode": "js"})
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                tool._run("https://example.com")

        mock_sync_client.scrape.assert_called_once_with(
            "https://example.com", mode="js"
        )

    def test_scrape_error_returns_message(self, mock_sync_client):
        mock_sync_client.scrape.side_effect = Exception("Connection refused")

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://fail.com")

        assert "Error scraping" in result
        assert "Connection refused" in result

    def test_empty_content(self, mock_sync_client):
        mock_sync_client.scrape.return_value = EMPTY_RESPONSE

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://example.com/empty")

        assert "No content" in result

    def test_include_metadata(self, mock_sync_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool(include_metadata=True)
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://example.com/article")

        assert "Title: Example Article" in result
        assert "Author: Jane Doe" in result
        assert "---" in result
        assert "article body" in result


# ---------------------------------------------------------------------------
# Async execution tests
# ---------------------------------------------------------------------------


class TestAsyncRun:
    def test_async_scrape(self, mock_async_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()

            async def run():
                with patch("alterlab.AlterLab", return_value=mock_async_client):
                    return await tool._arun("https://example.com/article")

            result = asyncio.get_event_loop().run_until_complete(run())
        assert "Example Article" in result

    def test_async_error_returns_message(self, mock_async_client):
        mock_async_client.scrape.side_effect = Exception("Timeout")

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()

            async def run():
                with patch("alterlab.AlterLab", return_value=mock_async_client):
                    return await tool._arun("https://fail.com")

            result = asyncio.get_event_loop().run_until_complete(run())
        assert "Error scraping" in result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_input_schema(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()

        schema = tool.args_schema.model_json_schema()
        assert "url" in schema["properties"]
        assert schema["required"] == ["url"]

    def test_invoke_interface(self, mock_sync_client):
        """Test that invoke() works (the standard LangChain agent call)."""
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool.invoke("https://example.com")

        assert "Example Article" in result


# ---------------------------------------------------------------------------
# AlterLabSearchTool tests (#36916)
# ---------------------------------------------------------------------------

SEARCH_RESPONSE: Dict[str, Any] = {
    "results": [
        {
            "position": 1,
            "title": "First",
            "url": "https://a.example",
            "snippet": "alpha",
        },
        {"position": 2, "title": "Second", "url": "https://b.example", "snippet": ""},
    ]
}


class TestSearchTool:
    def test_sync_search_formats_results(self):
        from langchain_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.return_value = SEARCH_RESPONSE
        tool = AlterLabSearchTool(
            api_key="sk_test", num_results=2, params={"engine": "google"}
        )
        with patch("alterlab.AlterLabSync", return_value=client):
            out = tool._run("web scraping")
        assert "1. First\n   https://a.example\n   alpha" in out
        assert "2. Second" in out
        client.search.assert_called_once_with(
            "web scraping", num_results=2, engine="google"
        )
        client.close.assert_called_once()

    def test_search_includes_unified_page_content(self):
        from langchain_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.return_value = {
            "results": [
                {
                    "title": "T",
                    "url": "https://a.example",
                    "snippet": "s",
                    "content": {"markdown": "# Head\nbody"},
                }
            ]
        }
        tool = AlterLabSearchTool(api_key="sk_test")
        with patch("alterlab.AlterLabSync", return_value=client):
            out = tool._run("q")
        assert "   # Head\n   body" in out

    def test_empty_results(self):
        from langchain_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.return_value = {"results": []}
        with patch("alterlab.AlterLabSync", return_value=client):
            out = AlterLabSearchTool(api_key="sk_test")._run("nothing")
        assert out.startswith("No search results found")

    def test_error_returns_message(self):
        from langchain_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.side_effect = RuntimeError("boom")
        with patch("alterlab.AlterLabSync", return_value=client):
            out = AlterLabSearchTool(api_key="sk_test")._run("q")
        assert "Error searching" in out and "boom" in out
        client.close.assert_called_once()

    def test_async_search(self, mock_async_client):
        from langchain_alterlab import AlterLabSearchTool

        mock_async_client.search.return_value = SEARCH_RESPONSE
        with patch("alterlab.AlterLab", return_value=mock_async_client):
            out = asyncio.run(AlterLabSearchTool(api_key="sk_test")._arun("q"))
        assert "1. First" in out
