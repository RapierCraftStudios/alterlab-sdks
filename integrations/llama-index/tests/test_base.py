"""Unit tests for AlterLabReader."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


def _make_scrape_result(
    markdown: str = "# Hello\n\nWorld",
    title: str = "Test Page",
    status_code: int = 200,
    tier_used: str = "1",
    credits: int = 1000,
) -> Dict[str, Any]:
    """Build a minimal fake AlterLab scrape response."""
    return {
        "markdown": markdown,
        "text": "Hello World",
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
def reader(mock_sync_client):
    """Return an AlterLabReader with a mocked AlterLabSync client."""
    with patch(
        "llama_index.readers.alterlab.base.AlterLabSync",
        return_value=mock_sync_client,
    ):
        # Also patch AdvancedOptions import so no real network calls happen
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            r = AlterLabReader(api_key="sk_live_test_key")
            r._client = mock_sync_client
            return r


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


def test_reader_defaults():
    """AlterLabReader initialises with expected default values."""
    with patch("llama_index.readers.alterlab.base.AlterLabSync"):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            r = AlterLabReader(api_key="sk_live_test")
            assert r.mode == "auto"
            assert r.output_format == "markdown"
            assert r.render_js is False


def test_invalid_mode_raises():
    with patch("llama_index.readers.alterlab.base.AlterLabSync"):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            with pytest.raises(ValueError, match="mode must be one of"):
                AlterLabReader(api_key="sk_live_test", mode="invalid")


def test_invalid_output_format_raises():
    with patch("llama_index.readers.alterlab.base.AlterLabSync"):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            with pytest.raises(ValueError, match="output_format must be one of"):
                AlterLabReader(api_key="sk_live_test", output_format="xml")


def test_reader_uses_env_var_when_api_key_omitted(monkeypatch):
    """AlterLabReader falls back to ALTERLAB_API_KEY when api_key is omitted."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    with patch("llama_index.readers.alterlab.base.AlterLabSync") as mock_sync:
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            reader = AlterLabReader()
            assert reader._api_key == "sk_live_from_env"
            mock_sync.assert_called_once_with(
                api_key="sk_live_from_env", base_url="https://api.alterlab.io"
            )


def test_reader_explicit_api_key_wins_over_env(monkeypatch):
    """An explicit api_key argument takes precedence over ALTERLAB_API_KEY."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    with patch("llama_index.readers.alterlab.base.AlterLabSync"):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            reader = AlterLabReader(api_key="sk_live_explicit")
            assert reader._api_key == "sk_live_explicit"


def test_reader_missing_api_key_raises(monkeypatch):
    """AlterLabReader raises ValueError when no api_key and no env var are set."""
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
    with patch("llama_index.readers.alterlab.base.AlterLabSync"):
        with patch("llama_index.readers.alterlab.base.AdvancedOptions"):
            from llama_index.readers.alterlab import AlterLabReader

            with pytest.raises(ValueError, match="AlterLab API key is required"):
                AlterLabReader()


# ---------------------------------------------------------------------------
# load_data tests
# ---------------------------------------------------------------------------


def test_load_data_single_url(reader, mock_sync_client):
    """load_data returns one Document for one URL."""
    docs = reader.load_data(["https://example.com"])
    assert len(docs) == 1
    doc = docs[0]
    assert doc.text == "# Hello\n\nWorld"
    assert doc.metadata["source"] == "https://example.com"
    assert doc.metadata["title"] == "Test Page"
    assert doc.metadata["status_code"] == 200
    assert doc.metadata["tier_used"] == "1"


def test_load_data_multiple_urls(reader, mock_sync_client):
    """load_data returns one Document per URL."""
    urls = [
        "https://example.com/page-1",
        "https://example.com/page-2",
        "https://example.com/page-3",
    ]
    mock_sync_client.scrape.return_value = _make_scrape_result()
    docs = reader.load_data(urls)
    assert len(docs) == 3
    assert mock_sync_client.scrape.call_count == 3
    for i, doc in enumerate(docs):
        assert doc.metadata["source"] == urls[i]


def test_load_data_mode_override(reader, mock_sync_client):
    """mode keyword arg is forwarded to the scrape call."""
    reader.load_data(["https://example.com"], mode="js")
    call_kwargs = mock_sync_client.scrape.call_args[1]
    assert call_kwargs.get("mode") == "js"


def test_load_data_output_format_override(reader, mock_sync_client):
    """output_format override is forwarded as formats=[fmt]."""
    mock_sync_client.scrape.return_value = {
        "text": "plain text",
        "metadata": {"title": "T", "status_code": 200},
        "billing": {},
    }
    docs = reader.load_data(["https://example.com"], output_format="text")
    assert docs[0].text == "plain text"
    call_kwargs = mock_sync_client.scrape.call_args[1]
    assert "text" in call_kwargs.get("formats", [])


def test_load_data_skips_failed_urls(reader, mock_sync_client):
    """Failed scrapes are skipped with a warning, not raising."""
    mock_sync_client.scrape.side_effect = [
        RuntimeError("connection refused"),
        _make_scrape_result(markdown="OK"),
    ]
    docs = reader.load_data(["https://broken.example.com", "https://ok.example.com"])
    assert len(docs) == 1
    assert docs[0].text == "OK"


def test_load_data_extra_info_merged(reader, mock_sync_client):
    """extra_info keys are merged into Document metadata."""
    docs = reader.load_data(
        ["https://example.com"],
        extra_info={"dataset": "test-set", "batch_id": "123"},
    )
    assert docs[0].metadata["dataset"] == "test-set"
    assert docs[0].metadata["batch_id"] == "123"


def test_load_data_invalid_mode_raises(reader):
    """Passing an invalid mode to load_data raises ValueError."""
    with pytest.raises(ValueError, match="mode must be one of"):
        reader.load_data(["https://example.com"], mode="ftp")


# ---------------------------------------------------------------------------
# load_data_single tests
# ---------------------------------------------------------------------------


def test_load_data_single_returns_document(reader, mock_sync_client):
    """load_data_single returns a single Document."""
    doc = reader.load_data_single("https://example.com")
    assert doc.text == "# Hello\n\nWorld"
    assert doc.metadata["source"] == "https://example.com"


# ---------------------------------------------------------------------------
# Content extraction tests
# ---------------------------------------------------------------------------


def test_extract_content_format_content(reader, mock_sync_client):
    """The 'content' format extracts body_markdown from nested dict."""
    mock_sync_client.scrape.return_value = {
        "content": {
            "content": {
                "body_markdown": "## Extracted\n\nBody.",
                "content_hash": "abc123",
            }
        },
        "metadata": {},
        "billing": {},
    }
    docs = reader.load_data(["https://example.com"], output_format="content")
    assert docs[0].text == "## Extracted\n\nBody."


def test_extract_content_fallback_chain(reader, mock_sync_client):
    """When requested format is absent, falls back to 'text'."""
    mock_sync_client.scrape.return_value = {
        "text": "fallback text",
        "metadata": {},
        "billing": {},
    }
    # 'rag' format not in response → should fall back to 'text'
    docs = reader.load_data(["https://example.com"], output_format="rag")
    assert docs[0].text == "fallback text"


def test_metadata_excludes_none_values(reader, mock_sync_client):
    """None-valued metadata keys are stripped from the Document metadata."""
    mock_sync_client.scrape.return_value = {
        "markdown": "text",
        "metadata": {"title": "T"},  # no status_code
        "billing": {},  # no tier_used
    }
    docs = reader.load_data(["https://example.com"])
    meta = docs[0].metadata
    assert "status_code" not in meta
    assert "tier_used" not in meta


# ---------------------------------------------------------------------------
# Resource cleanup tests
# ---------------------------------------------------------------------------


def test_close_delegates_to_client(reader, mock_sync_client):
    """close() calls close() on the underlying AlterLabSync client."""
    reader.close()
    mock_sync_client.close.assert_called_once()


def test_context_manager_enter_returns_self(reader):
    """__enter__ returns the reader instance itself."""
    with reader as r:
        assert r is reader


def test_context_manager_exit_closes_client(reader, mock_sync_client):
    """Exiting the `with` block closes the underlying client."""
    with reader:
        mock_sync_client.close.assert_not_called()
    mock_sync_client.close.assert_called_once()


def test_context_manager_exit_closes_client_on_exception(reader, mock_sync_client):
    """The client is closed even if an exception is raised inside the block."""
    with pytest.raises(ValueError):
        with reader:
            raise ValueError("boom")
    mock_sync_client.close.assert_called_once()


def test_close_is_idempotent(reader, mock_sync_client):
    """Calling close() twice does not raise and only closes the client once."""
    reader.close()
    reader.close()  # must not raise, e.g. RuntimeError: Event loop is closed
    mock_sync_client.close.assert_called_once()


def test_double_context_manager_exit_is_idempotent(reader, mock_sync_client):
    """Using the reader as a context manager after an explicit close() is safe."""
    reader.close()
    with reader:
        pass
    mock_sync_client.close.assert_called_once()
