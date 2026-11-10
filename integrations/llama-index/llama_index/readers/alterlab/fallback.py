"""Blocked-fetch fallback for LlamaIndex agents.

``FetchFallbackAdapter`` tries the caller's own fetch first and retries the URL
through AlterLab only when the response carries a block signal: an HTTP 403/429, a
bot-protection challenge page, a CAPTCHA, or an empty JavaScript shell. Any other outcome
(a normal page, a 404, a network error) is returned or raised untouched, so AlterLab credits
are spent only when the plain fetch was actually blocked.

Usage::

    import requests
    from llama_index.readers.alterlab import AlterLabBlockedFetchFallback

    fallback = AlterLabBlockedFetchFallback(fetch=lambda url: requests.get(url, timeout=20))
    tool = fallback.to_tool()  # FunctionTool for a LlamaIndex agent
"""

import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

BLOCK_STATUS_CODES = frozenset({403, 429})

_CHALLENGE_MARKERS = re.compile(
    r"just a moment|checking your browser|verify you are (?:a )?human|attention required"
    r"|access denied|captcha|are you a robot|unusual traffic|enable javascript and cookies"
    r"|px-captcha|challenge-platform|_incapsula_|datadome",
    re.IGNORECASE,
)
_SCRIPT_OR_STYLE = re.compile(
    r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAGS = re.compile(r"<[^>]+>")
_JS_REQUIRED = re.compile(r"enable javascript|requires javascript", re.IGNORECASE)
_EMPTY_SHELL_MAX_CHARS = 80


def _visible_text(html: str) -> str:
    without_blocks = _SCRIPT_OR_STYLE.sub(" ", html)
    return " ".join(_TAGS.sub(" ", without_blocks).split())


def is_blocked(status_code: Optional[int], body: str) -> bool:
    """Return True when a plain fetch result looks blocked rather than served."""
    if status_code in BLOCK_STATUS_CODES:
        return True
    if status_code is not None and not 200 <= status_code < 300:
        return False
    if _CHALLENGE_MARKERS.search(body):
        return True
    looks_like_html = (
        "<html" in body.lower() or "<body" in body.lower() or "<div" in body.lower()
    )
    if looks_like_html:
        if len(_visible_text(body)) <= _EMPTY_SHELL_MAX_CHARS:
            return True
        return False
    if _JS_REQUIRED.search(body):
        return len(body.strip()) <= _EMPTY_SHELL_MAX_CHARS * 4
    return not body.strip()


def _unpack(result: Any) -> "tuple[Optional[int], str]":
    """Accept a str, a ``(status, text)`` tuple, or a requests/httpx-style response."""
    if isinstance(result, str):
        return None, result
    if isinstance(result, tuple) and len(result) == 2:
        status, text = result
        return status, text or ""
    status = getattr(result, "status_code", None)
    text = getattr(result, "text", "")
    return status, text if isinstance(text, str) else str(text or "")


class FetchFallbackAdapter:
    """Fetch a URL with the caller's fetch; retry via AlterLab only if it was blocked.

    Args:
        fetch: Caller's fetch: returns a str, a ``(status_code, text)`` tuple, or a
            response object with ``status_code`` and ``text``.
        fallback: Object with ``scrape(url) -> str`` used on a block signal. Defaults to
            :class:`~llama_index.readers.alterlab.AlterLabScrapeTool`.
    """

    def __init__(
        self, fetch: Callable[[str], Any], fallback: Optional[Any] = None
    ) -> None:
        self._fetch = fetch
        self._fallback = fallback

    def _fallback_tool(self) -> Any:
        if self._fallback is None:
            from llama_index.readers.alterlab.tools import AlterLabScrapeTool

            self._fallback = AlterLabScrapeTool()
        return self._fallback

    def fetch(self, url: str) -> str:
        """Return the page content, retrying through AlterLab if the fetch was blocked."""
        status, body = _unpack(self._fetch(url))
        if not is_blocked(status, body):
            return body
        logger.info(
            "Blocked fetch for %s (status=%s); retrying via AlterLab", url, status
        )
        return self._fallback_tool().scrape(url)

    def to_tool(self) -> Any:
        """Convert to a LlamaIndex FunctionTool."""
        from llama_index.core.tools import FunctionTool

        return FunctionTool.from_defaults(
            fn=self.fetch,
            name="fetch_with_alterlab_fallback",
            description=(
                "Read a web page. Tries a normal fetch first and automatically retries "
                "through AlterLab when that fetch returns 403/429, a bot-protection "
                "challenge page, a CAPTCHA, or an empty JavaScript shell. Input is a URL; "
                "returns the page content."
            ),
        )
