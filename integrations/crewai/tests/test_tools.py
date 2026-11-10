"""Tests for CrewAI AlterLab tools."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from crewai_alterlab.tools import AlterLabCrawlTool, AlterLabScrapeTool

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
    "response_time_ms": 300,
    "billing": {
        "total_credits": 2,
        "tier_used": "2",
    },
}

EMPTY_RESPONSE: Dict[str, Any] = {
    "url": "https://example.com/empty",
    "status_code": 200,
    "content": {},
}

SAMPLE_CRAWL_RESPONSE: Dict[str, Any] = {
    "pages": [
        {
            "url": "https://example.com/page1",
            "status_code": 200,
            "content": {
                "markdown": "# Page 1\n\nFirst page content.",
            },
        },
        {
            "url": "https://example.com/page2",
            "status_code": 200,
            "content": {
                "markdown": "# Page 2\n\nSecond page content.",
            },
        },
    ],
}


@pytest.fixture()
def mock_sync_client():
    """Create a mock AlterLabSync client."""
    client = MagicMock()
    client.scrape.return_value = SAMPLE_RESPONSE
    client.close = MagicMock()
    return client


@pytest.fixture()
def mock_crawl_client():
    """Create a mock AlterLabSync client for crawling."""
    client = MagicMock()
    client.crawl_and_wait.return_value = SAMPLE_CRAWL_RESPONSE
    client.close = MagicMock()
    return client


# ---------------------------------------------------------------------------
# AlterLabScrapeTool tests
# ---------------------------------------------------------------------------


class TestScrapeToolInit:
    def test_init_with_env_key(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            assert tool.name == "AlterLab Scrape"
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


class TestScrapeToolRun:
    def test_scrape_returns_content(self, mock_sync_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://example.com/article")

        assert "Example Article" in result
        assert "article body" in result
        mock_sync_client.scrape.assert_called_once_with("https://example.com/article")
        mock_sync_client.close.assert_called_once()

    def test_scrape_error_returns_message(self, mock_sync_client):
        mock_sync_client.scrape.side_effect = Exception("Connection refused")

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://fail.com")

        assert "Error scraping" in result

    def test_empty_content(self, mock_sync_client):
        mock_sync_client.scrape.return_value = EMPTY_RESPONSE

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool()
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                result = tool._run("https://example.com/empty")

        assert "No content" in result

    def test_scrape_with_params(self, mock_sync_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabScrapeTool(scrape_params={"mode": "js"})
            with patch("alterlab.AlterLabSync", return_value=mock_sync_client):
                tool._run("https://example.com")

        mock_sync_client.scrape.assert_called_once_with(
            "https://example.com", mode="js"
        )


# ---------------------------------------------------------------------------
# AlterLabCrawlTool tests
# ---------------------------------------------------------------------------


class TestCrawlToolInit:
    def test_init_with_env_key(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabCrawlTool()
            assert tool.name == "AlterLab Crawl"
            assert "crawl" in tool.description.lower()

    def test_init_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ALTERLAB_API_KEY", None)
            with pytest.raises(ValueError, match="API key is required"):
                AlterLabCrawlTool()


class TestCrawlToolRun:
    def test_crawl_returns_combined_content(self, mock_crawl_client):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabCrawlTool()
            with patch("alterlab.AlterLabSync", return_value=mock_crawl_client):
                result = tool._run("https://example.com", max_pages=5)

        assert "Page 1" in result
        assert "Page 2" in result
        assert "---" in result
        mock_crawl_client.crawl_and_wait.assert_called_once_with(
            "https://example.com",
            max_pages=5,
            formats=["markdown"],
            poll_timeout=300.0,
        )
        mock_crawl_client.close.assert_called_once()

    def test_crawl_error_returns_message(self, mock_crawl_client):
        mock_crawl_client.crawl_and_wait.side_effect = Exception("Timeout")

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabCrawlTool()
            with patch("alterlab.AlterLabSync", return_value=mock_crawl_client):
                result = tool._run("https://fail.com")

        assert "Error crawling" in result

    def test_crawl_no_pages(self, mock_crawl_client):
        mock_crawl_client.crawl_and_wait.return_value = {"pages": []}

        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabCrawlTool()
            with patch("alterlab.AlterLabSync", return_value=mock_crawl_client):
                result = tool._run("https://example.com")

        assert "No pages" in result

    def test_crawl_polls_to_completion(self):
        """Real AlterLabSync: start -> poll (pending) -> poll (completed) -> pages."""
        from unittest.mock import AsyncMock

        start = AsyncMock(return_value={"crawl_id": "c1"})
        poll = AsyncMock(
            side_effect=[
                {"status": "running", "pages": []},
                {"status": "completed", **SAMPLE_CRAWL_RESPONSE},
            ]
        )
        with (
            patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}),
            patch("alterlab.client.AlterLab.crawl", start),
            patch("alterlab.client.AlterLab.get_crawl", poll),
            patch("alterlab.client.asyncio.sleep", AsyncMock()),
        ):
            result = AlterLabCrawlTool()._run("https://example.com", max_pages=2)

        start.assert_awaited_once()
        assert poll.await_count == 2
        assert poll.await_args.kwargs == {"include_results": True}
        assert "Page 1" in result
        assert "Page 2" in result

    def test_crawl_timeout_returns_message(self):
        from alterlab import AlterLabTimeoutError

        client = MagicMock()
        client.crawl_and_wait.side_effect = AlterLabTimeoutError("too slow")
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_test_abc"}):
            tool = AlterLabCrawlTool(poll_timeout=1.0)
            with patch("alterlab.AlterLabSync", return_value=client):
                result = tool._run("https://example.com")

        assert "Error crawling" in result
        assert client.crawl_and_wait.call_args.kwargs["poll_timeout"] == 1.0


# ---------------------------------------------------------------------------
# AlterLabSearchTool tests (#36916)
# ---------------------------------------------------------------------------

_SEARCH_RESPONSE = {
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
    def test_search_formats_results(self):
        from crewai_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.return_value = _SEARCH_RESPONSE
        tool = AlterLabSearchTool(
            api_key="sk_test", num_results=2, search_params={"engine": "bing"}
        )
        with patch("alterlab.AlterLabSync", return_value=client):
            out = tool._run("web scraping")
        assert "1. First\n   https://a.example\n   alpha" in out
        assert "2. Second" in out
        client.search.assert_called_once_with(
            "web scraping", num_results=2, engine="bing"
        )
        client.close.assert_called_once()

    def test_empty_results(self):
        from crewai_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.return_value = {"results": []}
        with patch("alterlab.AlterLabSync", return_value=client):
            out = AlterLabSearchTool(api_key="sk_test")._run("nothing")
        assert out.startswith("No search results found")

    def test_error_returns_message(self):
        from crewai_alterlab import AlterLabSearchTool

        client = MagicMock()
        client.search.side_effect = RuntimeError("boom")
        with patch("alterlab.AlterLabSync", return_value=client):
            out = AlterLabSearchTool(api_key="sk_test")._run("q")
        assert "Error searching" in out and "boom" in out
        client.close.assert_called_once()
