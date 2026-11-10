"""Shared AlterLab API wrapper used by CrewAI tools.

Centralises client construction and response-to-content extraction so that
tool classes stay thin.
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
