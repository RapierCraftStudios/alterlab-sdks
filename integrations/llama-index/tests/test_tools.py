"""Unit tests for AlterLabScrapeTool."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


def _make_scrape_result(
    markdown: str = "# Example Article\n\nThis is the article body.",
    title: str = "Example Article",
    status_code: int = 200,
    tier_used: str = "2",
    credits: int = 2000,
) -> Dict[str, Any]:
    """Build a minimal fake AlterLab scrape response (same shape as test_base.py)."""
    return {
        "markdown": markdown,
        "text": "Example Article. This is the article body.",
        "metadata": {
            "title": title,
            "status_code": status_code,
        },
        "billing": {
            "tier_used": tier_used,
            "final_cost_microcents": credits,
        },
    }


@pytest.fixture()
def mock_sync_client():
    """Return a MagicMock substituting AlterLabSync."""
    mock = MagicMock()
    mock.scrape.return_value = _make_scrape_result()
    return mock


@pytest.fixture()
def tool(mock_sync_client):
    """Return an AlterLabScrapeTool with a mocked AlterLabSync client."""
    with patch(
        "llama_index.readers.alterlab.base.AlterLabSync",
        return_value=mock_sync_client,
    ):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabScrapeTool

            t = AlterLabScrapeTool(api_key="sk_live_test_key")
            t._reader._client = mock_sync_client
            return t


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestToolInit:
    def test_init_uses_env_var_when_api_key_omitted(self, monkeypatch):
        """api_key falls back to ALTERLAB_API_KEY when omitted (delegates to AlterLabReader)."""
        monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                t = AlterLabScrapeTool()
                assert t._reader._api_key == "sk_live_from_env"

    def test_init_explicit_api_key_wins_over_env(self, monkeypatch):
        """An explicit api_key argument takes precedence over ALTERLAB_API_KEY."""
        monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                t = AlterLabScrapeTool(api_key="sk_live_explicit")
                assert t._reader._api_key == "sk_live_explicit"

    def test_init_missing_api_key_raises(self, monkeypatch):
        """Raises ValueError (not TypeError) when neither api_key nor the env var are set."""
        monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                with pytest.raises(ValueError, match="AlterLab API key is required"):
                    AlterLabScrapeTool()

    def test_init_with_explicit_key(self):
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                t = AlterLabScrapeTool(api_key="sk_live_xyz")
                assert t._reader._api_key == "sk_live_xyz"

    def test_init_defaults(self):
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                t = AlterLabScrapeTool(api_key="sk_live_test")
                assert t._reader.mode == "auto"
                assert t._reader.output_format == "markdown"

    def test_init_custom_mode_and_format(self):
        with patch("llama_index.readers.alterlab.base.AlterLabSync"):
            with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
                from llama_index.readers.alterlab import AlterLabScrapeTool

                t = AlterLabScrapeTool(
                    api_key="sk_live_test", mode="js", output_format="text"
                )
                assert t._reader.mode == "js"
                assert t._reader.output_format == "text"


# ---------------------------------------------------------------------------
# Scrape tests
# ---------------------------------------------------------------------------


class TestScrape:
    def test_scrape_returns_content(self, tool, mock_sync_client):
        result = tool.scrape("https://example.com/article")

        assert "Example Article" in result
        assert "article body" in result
        mock_sync_client.scrape.assert_called_once()
        called_url = mock_sync_client.scrape.call_args[0][0]
        assert called_url == "https://example.com/article"

    def test_scrape_forwards_kwargs(self, tool, mock_sync_client):
        tool.scrape("https://example.com", mode="js")

        call_kwargs = mock_sync_client.scrape.call_args[1]
        assert call_kwargs.get("mode") == "js"

    def test_scrape_error_returns_message(self, tool, mock_sync_client):
        mock_sync_client.scrape.side_effect = Exception("Connection refused")

        result = tool.scrape("https://fail.com")

        assert "Error scraping" in result
        assert "Connection refused" in result

    def test_empty_content_returns_message(self, tool, mock_sync_client):
        mock_sync_client.scrape.return_value = {
            "markdown": "",
            "text": "",
            "metadata": {},
            "billing": {},
        }

        result = tool.scrape("https://example.com/empty")

        assert "No content" in result


# ---------------------------------------------------------------------------
# FunctionTool conversion tests
# ---------------------------------------------------------------------------


class TestToTool:
    def test_to_tool_returns_function_tool(self, tool):
        with patch("llama_index.core.tools.FunctionTool") as MockFT:
            MockFT.from_defaults.return_value = MagicMock()
            fn_tool = tool.to_tool()

            MockFT.from_defaults.assert_called_once()
            call_kwargs = MockFT.from_defaults.call_args
            assert call_kwargs[1]["name"] == "alterlab_scrape"
            assert "scrape" in call_kwargs[1]["description"].lower()
            assert fn_tool is not None


# ---------------------------------------------------------------------------
# Resource cleanup tests
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_delegates_to_reader(self, tool, mock_sync_client):
        """close() calls close() on the composed AlterLabReader's client."""
        tool.close()
        mock_sync_client.close.assert_called_once()

    def test_context_manager_enter_returns_self(self, tool):
        """__enter__ returns the tool instance itself."""
        with tool as t:
            assert t is tool

    def test_context_manager_exit_closes_client(self, tool, mock_sync_client):
        """Exiting the `with` block closes the composed reader's client."""
        with tool:
            mock_sync_client.close.assert_not_called()
        mock_sync_client.close.assert_called_once()

    def test_context_manager_exit_closes_client_on_exception(
        self, tool, mock_sync_client
    ):
        """The client is closed even if an exception is raised inside the block."""
        with pytest.raises(ValueError):
            with tool:
                raise ValueError("boom")
        mock_sync_client.close.assert_called_once()

    def test_close_is_idempotent(self, tool, mock_sync_client):
        """Calling close() twice does not raise and only closes once."""
        tool.close()
        tool.close()  # must not raise, e.g. RuntimeError: Event loop is closed
        mock_sync_client.close.assert_called_once()

    def test_double_context_manager_exit_is_idempotent(self, tool, mock_sync_client):
        """Using the tool as a context manager after an explicit close() is safe."""
        tool.close()
        with tool:
            pass
        mock_sync_client.close.assert_called_once()


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


@pytest.fixture()
def search_tool(mock_sync_client):
    with patch(
        "llama_index.readers.alterlab.base.AlterLabSync",
        return_value=mock_sync_client,
    ):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabSearchTool

            t = AlterLabSearchTool(
                api_key="sk_live_test_key", num_results=2, engine="google"
            )
            t._reader._client = mock_sync_client
            yield t


class TestSearchTool:
    def test_search_formats_results(self, search_tool, mock_sync_client):
        mock_sync_client.search.return_value = _SEARCH_RESPONSE
        out = search_tool.search("web scraping")
        assert "1. First\n   https://a.example\n   alpha" in out
        assert "2. Second" in out
        mock_sync_client.search.assert_called_once_with(
            "web scraping", num_results=2, engine="google"
        )

    def test_empty_results(self, search_tool, mock_sync_client):
        mock_sync_client.search.return_value = {"results": []}
        assert search_tool.search("nothing").startswith("No search results found")

    def test_error_returns_message(self, search_tool, mock_sync_client):
        mock_sync_client.search.side_effect = RuntimeError("boom")
        out = search_tool.search("q")
        assert "Error searching" in out and "boom" in out

    def test_close_idempotent(self, search_tool, mock_sync_client):
        search_tool.close()
        search_tool.close()
        mock_sync_client.close.assert_called_once()
