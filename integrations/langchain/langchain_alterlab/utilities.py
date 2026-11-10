"""Shared AlterLab API wrapper used by document loaders and tools.

Centralises client construction and response-to-content extraction so that
``AlterLabLoader`` and ``AlterLabScrapeTool`` stay thin.
"""

import os
from typing import Any, Dict, Optional


def get_api_key(api_key: Optional[str] = None) -> str:
    """Resolve the AlterLab API key.

    Args:
        api_key: Explicit key. Falls back to the ``ALTERLAB_API_KEY``
            environment variable.

    Returns:
        The resolved API key.

    Raises:
        ValueError: If no key can be resolved.
    """
    key = api_key or os.getenv("ALTERLAB_API_KEY", "")
    if not key:
        raise ValueError(
            "AlterLab API key is required. Pass api_key or set the "
            "ALTERLAB_API_KEY environment variable."
        )
    return key


def get_api_url(api_url: Optional[str] = None) -> str:
    """Resolve the AlterLab API base URL.

    Args:
        api_url: Explicit URL. Falls back to ``ALTERLAB_API_URL`` env var
            or ``https://api.alterlab.io``.

    Returns:
        The resolved base URL.
    """
    return api_url or os.getenv("ALTERLAB_API_URL") or "https://api.alterlab.io"


def extract_page_content(result: Dict[str, Any]) -> str:
    """Extract page content from an AlterLab API response.

    Priority order: markdown > text > html > raw content string.

    Args:
        result: AlterLab API response dictionary.

    Returns:
        Extracted content string, or empty string if no content found.
    """
    content = result.get("content")

    # Multi-format response (dict with format keys)
    if isinstance(content, dict):
        if content.get("markdown"):
            return content["markdown"]
        if content.get("text"):
            return content["text"]
        if content.get("html"):
            return content["html"]
        return ""

    # Legacy single-format response (string)
    if isinstance(content, str):
        return content

    return ""


def build_metadata(result: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    """Build a metadata dict from an AlterLab API response.

    Args:
        result: AlterLab API response dictionary.
        source_url: The URL that was scraped (used as fallback for ``source``).

    Returns:
        Metadata dictionary suitable for a LangChain ``Document``.
    """
    metadata: Dict[str, Any] = {"source": result.get("url", source_url)}

    # Content metadata
    if result.get("title"):
        metadata["title"] = result["title"]
    if result.get("author"):
        metadata["author"] = result["author"]
    if result.get("published_at"):
        metadata["published_at"] = result["published_at"]

    # Technical metadata
    if result.get("status_code") is not None:
        metadata["status_code"] = result["status_code"]
    if result.get("extraction_method"):
        metadata["extraction_method"] = result["extraction_method"]
    if result.get("response_time_ms") is not None:
        metadata["response_time_ms"] = result["response_time_ms"]

    # Billing metadata
    billing = result.get("billing")
    if isinstance(billing, dict):
        if billing.get("total_credits") is not None:
            metadata["credits_used"] = billing["total_credits"]
        if billing.get("tier_used"):
            metadata["tier_used"] = billing["tier_used"]
    elif result.get("credits_used") is not None:
        metadata["credits_used"] = result["credits_used"]

    # Extra metadata from the API response
    extra_meta = result.get("metadata")
    if isinstance(extra_meta, dict):
        for key, value in extra_meta.items():
            if key not in metadata and value is not None:
                metadata[key] = value

    return metadata
