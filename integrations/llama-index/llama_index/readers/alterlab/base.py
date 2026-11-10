"""AlterLab LlamaIndex data reader."""

import logging
import os
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional, Type

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

logger = logging.getLogger(__name__)

_VALID_MODES = ("auto", "html", "js", "pdf", "ocr")
_VALID_FORMATS = ("text", "html", "markdown", "rag", "content", "json", "json_v2")


class AlterLabReader(BaseReader):
    """LlamaIndex data reader that loads web pages via the AlterLab Scraping API.

    Uses the AlterLab Python SDK (``alterlab`` package) to scrape one or more
    URLs and convert the results into LlamaIndex :class:`Document` objects.
    The reader uses the synchronous :class:`~alterlab.AlterLabSync` client so
    that it fits naturally into LlamaIndex's synchronous ``BaseReader`` interface.

    Args:
        api_key: AlterLab API key (``sk_live_...``). If not provided, reads
            from the ``ALTERLAB_API_KEY`` environment variable.
        mode: Default scraping mode — ``"auto"`` (default), ``"html"``, ``"js"``,
            ``"pdf"``, or ``"ocr"``. Can be overridden per :meth:`load_data` call.
        output_format: Content format to extract — ``"markdown"`` (default),
            ``"text"``, ``"html"``, ``"rag"``, or ``"content"``.
        render_js: If ``True``, enable JavaScript rendering for all scrape calls
            (forces Tier 4). If ``False`` (default), the auto-escalation tier
            logic applies.
        base_url: Override the AlterLab API base URL. Useful for self-hosted
            deployments. Defaults to ``"https://api.alterlab.io"``.

    Example::

        from llama_index.readers.alterlab import AlterLabReader

        reader = AlterLabReader(api_key="sk_live_...")
        docs = reader.load_data(["https://example.com"])
        print(docs[0].text)

        # Or, with ALTERLAB_API_KEY set in the environment:
        reader = AlterLabReader()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        mode: Literal["auto", "html", "js", "pdf", "ocr"] = "auto",
        output_format: str = "markdown",
        render_js: bool = False,
        base_url: str = "https://api.alterlab.io",
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
        if output_format not in _VALID_FORMATS:
            raise ValueError(
                f"output_format must be one of {_VALID_FORMATS}, got {output_format!r}"
            )

        resolved_api_key = api_key or os.environ.get("ALTERLAB_API_KEY", "")
        if not resolved_api_key:
            raise ValueError(
                "AlterLab API key is required. Pass api_key= or set "
                "ALTERLAB_API_KEY environment variable."
            )

        # Lazy import to avoid hard dependency at module load time — allows the
        # reader to be imported even when ``alterlab`` is not yet installed, e.g.
        # in documentation builds or when doing type-checking only.
        try:
            from alterlab import AdvancedOptions, AlterLabSync
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'alterlab' package is required to use AlterLabReader. "
                "Install it with: pip install alterlab"
            ) from exc

        self._api_key = resolved_api_key
        self.mode = mode
        self.output_format = output_format
        self.render_js = render_js
        self._base_url = base_url

        advanced: Optional[Any] = None
        if render_js:
            advanced = AdvancedOptions(render_js=True)

        self._client = AlterLabSync(api_key=resolved_api_key, base_url=base_url)
        self._default_advanced = advanced
        self._closed = False

    # ------------------------------------------------------------------
    # Resource cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying AlterLab client and its event loop.

        The reader holds a persistent :class:`~alterlab.AlterLabSync` client
        for its lifetime (built once in ``__init__``), which owns its own
        ``asyncio`` event loop. Call this when the reader is no longer
        needed to release that client and loop, or use the reader as a
        context manager instead.

        Idempotent — a second call (e.g. an explicit ``close()`` after the
        reader was already used in a ``with`` block) is a no-op instead of
        raising ``RuntimeError: Event loop is closed``.
        """
        if self._closed:
            return
        self._client.close()
        self._closed = True

    def __enter__(self) -> "AlterLabReader":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit — closes the underlying client."""
        self.close()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_data(
        self,
        urls: List[str],
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        extra_info: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Document]:
        """Scrape one or more URLs and return them as LlamaIndex Documents.

        Args:
            urls: List of URLs to scrape.
            mode: Scraping mode override for this call. If ``None``, uses the
                reader's default ``mode``.
            output_format: Content format override for this call. If ``None``,
                uses the reader's default ``output_format``.
            extra_info: Additional metadata key/value pairs merged into each
                :class:`Document`'s metadata.
            **kwargs: Extra keyword arguments forwarded to
                :meth:`~alterlab.AlterLabSync.scrape`.

        Returns:
            A list of :class:`Document` objects, one per successfully scraped
            URL. Failed scrapes are skipped with a warning logged.
        """
        scrape_mode = mode or self.mode
        fmt = output_format or self.output_format

        if scrape_mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {_VALID_MODES}, got {scrape_mode!r}")

        documents: List[Document] = []

        for url in urls:
            try:
                result = self._scrape_one(url, scrape_mode, fmt, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AlterLabReader: failed to scrape %s — %s: %s",
                    url,
                    type(exc).__name__,
                    exc,
                )
                continue

            content = self._extract_content(result, fmt)
            metadata = self._build_metadata(url, result, extra_info)
            documents.append(Document(text=content, metadata=metadata))

        return documents

    def load_data_single(
        self,
        url: str,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        extra_info: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Document:
        """Scrape a single URL and return a LlamaIndex Document.

        Convenience wrapper around :meth:`load_data` for a single URL.

        Args:
            url: URL to scrape.
            mode: Scraping mode override.
            output_format: Content format override.
            extra_info: Additional metadata merged into the Document.
            **kwargs: Extra keyword arguments forwarded to
                :meth:`~alterlab.AlterLabSync.scrape`.

        Returns:
            A single :class:`Document`.

        Raises:
            RuntimeError: If the scrape fails.
        """
        scrape_mode = mode or self.mode
        fmt = output_format or self.output_format
        result = self._scrape_one(url, scrape_mode, fmt, **kwargs)
        content = self._extract_content(result, fmt)
        metadata = self._build_metadata(url, result, extra_info)
        return Document(text=content, metadata=metadata)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scrape_one(
        self, url: str, mode: str, fmt: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Execute a single scrape call and return the raw API response dict."""
        call_kwargs: Dict[str, Any] = dict(kwargs)
        call_kwargs.setdefault("formats", [fmt])
        if "mode" not in call_kwargs:
            call_kwargs["mode"] = mode
        if self._default_advanced is not None and "advanced" not in call_kwargs:
            call_kwargs["advanced"] = self._default_advanced
        return self._client.scrape(url, **call_kwargs)

    @staticmethod
    def _extract_content(result: Dict[str, Any], fmt: str) -> str:
        """Pull the requested format's text from the scrape response.

        Falls back to ``"text"`` and then the empty string when the requested
        format key is absent from the response.
        """
        if fmt == "content":
            # The "content" format returns a nested dict:
            # result["content"]["content"]["body_markdown"]
            content_block = result.get("content", {})
            if isinstance(content_block, dict):
                inner = content_block.get("content", {})
                if isinstance(inner, dict):
                    return inner.get("body_markdown", "") or ""
            return ""

        value = result.get(fmt)
        if value is not None and isinstance(value, str):
            return value

        # Graceful fallback chain
        for fallback_key in ("text", "markdown", "html"):
            fallback = result.get(fallback_key)
            if fallback and isinstance(fallback, str):
                logger.debug(
                    "AlterLabReader: format %r not in response; fell back to %r",
                    fmt,
                    fallback_key,
                )
                return fallback

        return ""

    @staticmethod
    def _build_metadata(
        url: str,
        result: Dict[str, Any],
        extra_info: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build the Document metadata dict from the scrape response."""
        api_meta = result.get("metadata") or {}
        billing = result.get("billing") or {}

        metadata: Dict[str, Any] = {
            "source": url,
            "title": api_meta.get("title", "") if isinstance(api_meta, dict) else "",
            "status_code": (
                api_meta.get("status_code") if isinstance(api_meta, dict) else None
            ),
            "tier_used": (
                billing.get("tier_used") if isinstance(billing, dict) else None
            ),
            "credits_charged": (
                billing.get("final_cost_microcents")
                if isinstance(billing, dict)
                else None
            ),
        }

        # Remove None values to keep metadata clean
        metadata = {k: v for k, v in metadata.items() if v is not None}

        if extra_info:
            metadata.update(extra_info)

        return metadata
