"""Tests for shared utilities."""

from typing import Any, Dict
from unittest.mock import patch

import pytest

from langchain_alterlab.utilities import (
    build_metadata,
    extract_page_content,
    get_api_key,
    get_api_url,
)

# ---------------------------------------------------------------------------
# get_api_key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_explicit_key(self):
        assert get_api_key("sk_test_abc") == "sk_test_abc"

    def test_env_key(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_env_123"}):
            assert get_api_key() == "sk_env_123"

    def test_explicit_overrides_env(self):
        with patch.dict("os.environ", {"ALTERLAB_API_KEY": "sk_env_123"}):
            assert get_api_key("sk_explicit") == "sk_explicit"

    def test_missing_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ALTERLAB_API_KEY", None)
            with pytest.raises(ValueError, match="API key is required"):
                get_api_key()


# ---------------------------------------------------------------------------
# get_api_url
# ---------------------------------------------------------------------------


class TestGetApiUrl:
    def test_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ALTERLAB_API_URL", None)
            assert get_api_url() == "https://api.alterlab.io"

    def test_explicit_url(self):
        assert get_api_url("https://custom.api.com") == "https://custom.api.com"

    def test_env_url(self):
        with patch.dict(
            "os.environ", {"ALTERLAB_API_URL": "https://staging.alterlab.io"}
        ):
            assert get_api_url() == "https://staging.alterlab.io"


# ---------------------------------------------------------------------------
# extract_page_content
# ---------------------------------------------------------------------------


class TestExtractPageContent:
    def test_markdown_priority(self):
        result: Dict[str, Any] = {
            "content": {
                "markdown": "# Hello",
                "text": "Hello",
                "html": "<h1>Hello</h1>",
            }
        }
        assert extract_page_content(result) == "# Hello"

    def test_text_fallback(self):
        result: Dict[str, Any] = {
            "content": {"text": "Hello text", "html": "<p>Hello</p>"}
        }
        assert extract_page_content(result) == "Hello text"

    def test_html_fallback(self):
        result: Dict[str, Any] = {"content": {"html": "<p>Only HTML</p>"}}
        assert extract_page_content(result) == "<p>Only HTML</p>"

    def test_string_content(self):
        result: Dict[str, Any] = {"content": "Plain string content"}
        assert extract_page_content(result) == "Plain string content"

    def test_empty_dict_content(self):
        result: Dict[str, Any] = {"content": {}}
        assert extract_page_content(result) == ""

    def test_none_content(self):
        result: Dict[str, Any] = {"content": None}
        assert extract_page_content(result) == ""

    def test_missing_content(self):
        result: Dict[str, Any] = {}
        assert extract_page_content(result) == ""


# ---------------------------------------------------------------------------
# build_metadata
# ---------------------------------------------------------------------------


class TestBuildMetadata:
    def test_full_metadata(self):
        result: Dict[str, Any] = {
            "url": "https://example.com",
            "title": "Test",
            "author": "Author",
            "published_at": "2026-01-01",
            "status_code": 200,
            "extraction_method": "algorithmic",
            "response_time_ms": 100,
            "billing": {"total_credits": 5, "tier_used": "3"},
            "metadata": {"language": "en"},
        }
        meta = build_metadata(result, "https://fallback.com")
        assert meta["source"] == "https://example.com"
        assert meta["title"] == "Test"
        assert meta["author"] == "Author"
        assert meta["credits_used"] == 5
        assert meta["tier_used"] == "3"
        assert meta["language"] == "en"

    def test_legacy_credits(self):
        result: Dict[str, Any] = {
            "url": "https://example.com",
            "credits_used": 1,
        }
        meta = build_metadata(result, "https://example.com")
        assert meta["credits_used"] == 1

    def test_source_fallback(self):
        result: Dict[str, Any] = {}
        meta = build_metadata(result, "https://fallback.com")
        assert meta["source"] == "https://fallback.com"

    def test_extra_metadata_no_overwrite(self):
        result: Dict[str, Any] = {
            "url": "https://example.com",
            "title": "Real Title",
            "metadata": {"title": "Meta Title", "custom_field": "value"},
        }
        meta = build_metadata(result, "https://example.com")
        assert meta["title"] == "Real Title"
        assert meta["custom_field"] == "value"
