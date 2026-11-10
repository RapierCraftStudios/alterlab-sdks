"""AlterLab scrape tool for LlamaIndex agents.

Provides ``AlterLabScrapeTool`` — a LlamaIndex ``FunctionTool`` factory that
allows agents to scrape web pages on demand via the AlterLab API.

Usage with an agent::

    from llama_index.readers.alterlab import AlterLabScrapeTool

    tool = AlterLabScrapeTool(api_key="sk_live_...")
    function_tool = tool.to_tool()
"""

import logging
from types import TracebackType
from typing import Any, Literal, Optional, Type

from llama_index.readers.alterlab.base import AlterLabReader

logger = logging.getLogger(__name__)


class AlterLabScrapeTool:
    """Tool that scrapes a single web page via the AlterLab API.

    Wraps :class:`~llama_index.readers.alterlab.AlterLabReader` to provide a
    simple ``scrape(url) -> str`` interface, plus a :meth:`to_tool` conversion
    to a LlamaIndex ``FunctionTool``, for use with LlamaIndex agents that need
    to fetch and read web page content on demand.

    Args:
        api_key: AlterLab API key (``sk_live_...``). If not provided, reads
            from the ``ALTERLAB_API_KEY`` environment variable.
        mode: Default scraping mode — ``"auto"`` (default), ``"html"``, ``"js"``,
            ``"pdf"``, or ``"ocr"``. Passed through to the underlying
            :class:`AlterLabReader`.
        output_format: Content format to extract — ``"markdown"`` (default),
            ``"text"``, ``"html"``, ``"rag"``, or ``"content"``. Passed through
            to the underlying :class:`AlterLabReader`.
        render_js: If ``True``, enable JavaScript rendering for all scrape calls
            (forces Tier 4). If ``False`` (default), the auto-escalation tier
            logic applies.
        base_url: Override the AlterLab API base URL. Useful for self-hosted
            deployments. Defaults to ``"https://api.alterlab.io"``.

    Example::

        from llama_index.readers.alterlab import AlterLabScrapeTool

        tool = AlterLabScrapeTool(api_key="sk_live_...")
        result = tool.scrape("https://example.com")
        print(result)

    With a LlamaIndex agent::

        from llama_index.core.agent import ReActAgent
        from llama_index.llms.openai import OpenAI
        from llama_index.readers.alterlab import AlterLabScrapeTool

        scrape_tool = AlterLabScrapeTool(api_key="sk_live_...")
        agent = ReActAgent.from_tools(
            [scrape_tool.to_tool()],
            llm=OpenAI(model="gpt-4"),
        )
        response = agent.chat("Scrape https://example.com and summarise it")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        mode: Literal["auto", "html", "js", "pdf", "ocr"] = "auto",
        output_format: str = "markdown",
        render_js: bool = False,
        base_url: str = "https://api.alterlab.io",
    ) -> None:
        # Delegate client construction, validation, and response parsing to
        # AlterLabReader — the tool is a thin single-URL wrapper around it, so
        # there is exactly one place in this package that talks to the
        # AlterLab API and interprets its response shape.
        self._reader = AlterLabReader(
            api_key=api_key,
            mode=mode,
            output_format=output_format,
            render_js=render_js,
            base_url=base_url,
        )
        self._closed = False

    def close(self) -> None:
        """Close the underlying AlterLab client and its event loop.

        The tool composes an :class:`~llama_index.readers.alterlab.AlterLabReader`
        (built once in ``__init__``), which itself holds a persistent client
        with its own ``asyncio`` event loop. Call this when the tool is no
        longer needed to release that resource, or use the tool as a context
        manager instead.

        Idempotent — a second call is a no-op instead of raising
        ``RuntimeError: Event loop is closed``.
        """
        if self._closed:
            return
        self._reader.close()
        self._closed = True

    def __enter__(self) -> "AlterLabScrapeTool":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit — closes the underlying reader/client."""
        self.close()

    def scrape(self, url: str, **kwargs: Any) -> str:
        """Scrape a URL and return its content as text.

        Args:
            url: The URL to scrape.
            **kwargs: Extra keyword arguments forwarded to
                :meth:`~llama_index.readers.alterlab.AlterLabReader.load_data_single`
                (e.g. ``mode``, ``output_format``, or any AlterLab scrape API
                parameter).

        Returns:
            Page content as a string, or an error message if the scrape
            failed or returned no content.
        """
        try:
            document = self._reader.load_data_single(url, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AlterLabScrapeTool: failed to scrape %s — %s: %s",
                url,
                type(exc).__name__,
                exc,
            )
            return f"Error scraping {url}: {exc}"

        if not document.text:
            return f"No content could be extracted from {url}"
        return document.text

    def to_tool(self) -> Any:
        """Convert to a LlamaIndex FunctionTool.

        Returns:
            A ``FunctionTool`` instance ready for use with LlamaIndex agents.
        """
        from llama_index.core.tools import FunctionTool

        return FunctionTool.from_defaults(
            fn=self.scrape,
            name="alterlab_scrape",
            description=(
                "Scrape a web page and return its content. "
                "Input is a URL string. Returns the page content as text. "
                "Useful for reading web pages, articles, documentation, or "
                "any publicly accessible URL."
            ),
        )


class AlterLabSearchTool:
    """LlamaIndex search tool backed by the AlterLab Search API.

    Reuses :class:`~llama_index.readers.alterlab.AlterLabReader` for client
    construction and cleanup, like :class:`AlterLabScrapeTool`.

    Example::

        tool = AlterLabSearchTool(api_key="sk_live_...", num_results=5)
        function_tool = tool.to_tool()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        num_results: int = 10,
        base_url: str = "https://api.alterlab.io",
        **search_params: Any,
    ) -> None:
        self._reader = AlterLabReader(api_key=api_key, base_url=base_url)
        self.num_results = num_results
        self.search_params = search_params
        self._closed = False

    def close(self) -> None:
        """Close the underlying client. Idempotent."""
        if self._closed:
            return
        self._reader.close()
        self._closed = True

    def __enter__(self) -> "AlterLabSearchTool":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def search(self, query: str, **kwargs: Any) -> str:
        """Run a web search and return numbered title/URL/snippet text.

        Returns an error message string if the search fails.
        """
        params = {"num_results": self.num_results, **self.search_params, **kwargs}
        try:
            result = self._reader._client.search(query, **params)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AlterLabSearchTool: search failed for %r — %s: %s",
                query,
                type(exc).__name__,
                exc,
            )
            return f"Error searching {query!r}: {exc}"

        items = result.get("results") or []
        if not items:
            return f"No search results found for {query!r}"
        lines = []
        for i, item in enumerate(items, start=1):
            pos = item.get("position") or i
            lines.append(f"{pos}. {item.get('title', '')}\n   {item.get('url', '')}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet']}")
            page = item.get("content")
            text = (page.get("markdown") or page.get("text")) if isinstance(page, dict) else None
            if text:
                # Unified search returns each page's concise content with the result.
                lines.append("   " + text.strip()[:1500].replace("\n", "\n   "))
        return "\n".join(lines)

    def to_tool(self) -> Any:
        """Convert to a LlamaIndex ``FunctionTool``."""
        from llama_index.core.tools import FunctionTool

        return FunctionTool.from_defaults(
            fn=self.search,
            name="alterlab_search",
            description=(
                "Search the web and return a numbered list of results with "
                "title, URL and snippet. Input is a search query string."
            ),
        )
