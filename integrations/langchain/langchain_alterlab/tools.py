"""AlterLab scrape tool for LangChain agents.

Provides ``AlterLabScrapeTool`` — a LangChain ``BaseTool`` that allows agents
to scrape web pages on demand via the AlterLab API and receive the content as
a string ready for downstream processing.

Usage with an agent::

    from langchain_alterlab import AlterLabScrapeTool

    tool = AlterLabScrapeTool()
    # In an agent:
    tools = [tool]
"""

import logging
from typing import Any, Dict, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_alterlab.utilities import (
    build_metadata,
    extract_page_content,
    get_api_key,
    get_api_url,
)

logger = logging.getLogger(__name__)


class _ScrapeInput(BaseModel):
    """Input schema for the AlterLab scrape tool."""

    url: str = Field(description="The URL of the web page to scrape.")


class AlterLabScrapeTool(BaseTool):
    """Tool that scrapes a web page using the AlterLab API.

    Returns the page content as a string (markdown preferred). Designed for
    use with LangChain agents that need to fetch and read web page content.

    Setup:
        Install the package and set the ``ALTERLAB_API_KEY`` environment
        variable::

            pip install langchain-alterlab
            export ALTERLAB_API_KEY="your-api-key"

    Usage:
        .. code-block:: python

            from langchain_alterlab import AlterLabScrapeTool

            tool = AlterLabScrapeTool()
            result = tool.invoke("https://example.com")
            print(result)

    With an agent:
        .. code-block:: python

            from langchain_openai import ChatOpenAI
            from langchain_alterlab import AlterLabScrapeTool

            llm = ChatOpenAI()
            tools = [AlterLabScrapeTool()]
            agent = llm.bind_tools(tools)
    """

    name: str = "alterlab_scrape"
    description: str = (
        "Scrape a web page and return its content. "
        "Input is a URL. Returns the page content as markdown text. "
        "Useful for reading web pages, articles, documentation, or any "
        "publicly accessible URL."
    )
    args_schema: Type[BaseModel] = _ScrapeInput

    api_key: Optional[str] = None
    """AlterLab API key. Defaults to ALTERLAB_API_KEY env var."""

    api_url: Optional[str] = None
    """AlterLab API base URL. Defaults to https://api.alterlab.io."""

    params: Dict[str, Any] = Field(default_factory=dict)
    """Additional parameters passed to the AlterLab scrape API."""

    include_metadata: bool = False
    """If True, prepend metadata (title, author, etc.) to the output."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise AlterLabScrapeTool.

        Validates the API key is available at construction time.

        Raises:
            ImportError: If the ``alterlab`` package is not installed.
            ValueError: If no API key can be resolved.
        """
        try:
            import alterlab  # noqa: F401
        except ImportError:
            raise ImportError(
                "Could not import alterlab python package. "
                "Please install it with `pip install alterlab`."
            )
        super().__init__(**kwargs)
        # Validate key is resolvable (raises ValueError if not)
        get_api_key(self.api_key)

    def _run(
        self,
        url: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Scrape a URL synchronously.

        Args:
            url: The URL to scrape.
            run_manager: Optional callback manager.

        Returns:
            Page content as a string, or an error message.
        """
        from alterlab import AlterLabSync

        resolved_key = get_api_key(self.api_key)
        resolved_url = get_api_url(self.api_url)

        client = AlterLabSync(api_key=resolved_key, base_url=resolved_url)
        try:
            result = client.scrape(url, **self.params)
            return self._format_result(result, url)
        except Exception as e:
            logger.warning("AlterLab scrape failed for %s: %s", url, e)
            return f"Error scraping {url}: {e}"
        finally:
            client.close()

    async def _arun(
        self,
        url: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Scrape a URL asynchronously.

        Args:
            url: The URL to scrape.
            run_manager: Optional callback manager.

        Returns:
            Page content as a string, or an error message.
        """
        from alterlab import AlterLab

        resolved_key = get_api_key(self.api_key)
        resolved_url = get_api_url(self.api_url)

        async with AlterLab(api_key=resolved_key, base_url=resolved_url) as client:
            try:
                result = await client.scrape(url, **self.params)
                return self._format_result(result, url)
            except Exception as e:
                logger.warning("AlterLab scrape failed for %s: %s", url, e)
                return f"Error scraping {url}: {e}"

    def _format_result(self, result: Dict[str, Any], url: str) -> str:
        """Format an AlterLab API response as a string.

        Args:
            result: AlterLab API response dictionary.
            url: The URL that was scraped.

        Returns:
            Formatted content string.
        """
        content = extract_page_content(result)
        if not content:
            return f"No content could be extracted from {url}"

        if not self.include_metadata:
            return content

        metadata = build_metadata(result, url)
        header_parts = []
        if metadata.get("title"):
            header_parts.append(f"Title: {metadata['title']}")
        if metadata.get("author"):
            header_parts.append(f"Author: {metadata['author']}")
        if metadata.get("published_at"):
            header_parts.append(f"Published: {metadata['published_at']}")
        header_parts.append(f"Source: {metadata.get('source', url)}")

        header = "\n".join(header_parts)
        return f"{header}\n---\n{content}"


def _format_search_results(result: Dict[str, Any], query: str) -> str:
    """Format a SERP response as numbered ``title / url / snippet`` text."""
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


class _SearchInput(BaseModel):
    """Input schema for the AlterLab search tool."""

    query: str = Field(description="The search query (max 500 characters).")


class AlterLabSearchTool(BaseTool):
    """Tool that runs a web search using the AlterLab Search API.

    Returns numbered results (title, URL, snippet) as a string.

    Usage:
        .. code-block:: python

            from langchain_alterlab import AlterLabSearchTool

            tool = AlterLabSearchTool(num_results=5)
            print(tool.invoke("web scraping api"))
    """

    name: str = "alterlab_search"
    description: str = (
        "Search the web and return a numbered list of results with title, "
        "URL and snippet. Input is a search query."
    )
    args_schema: Type[BaseModel] = _SearchInput

    api_key: Optional[str] = None
    """AlterLab API key. Defaults to ALTERLAB_API_KEY env var."""

    api_url: Optional[str] = None
    """AlterLab API base URL. Defaults to https://api.alterlab.io."""

    num_results: int = 10
    """Number of results to return (1-30)."""

    params: Dict[str, Any] = Field(default_factory=dict)
    """Additional parameters passed to the AlterLab search API (e.g. engine, domain)."""

    def __init__(self, **kwargs: Any) -> None:
        try:
            import alterlab  # noqa: F401
        except ImportError:
            raise ImportError(
                "Could not import alterlab python package. "
                "Please install it with `pip install alterlab`."
            )
        super().__init__(**kwargs)
        get_api_key(self.api_key)

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        from alterlab import AlterLabSync

        client = AlterLabSync(
            api_key=get_api_key(self.api_key), base_url=get_api_url(self.api_url)
        )
        try:
            result = client.search(query, num_results=self.num_results, **self.params)
            return _format_search_results(result, query)
        except Exception as e:
            logger.warning("AlterLab search failed for %r: %s", query, e)
            return f"Error searching {query!r}: {e}"
        finally:
            client.close()

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        from alterlab import AlterLab

        async with AlterLab(
            api_key=get_api_key(self.api_key), base_url=get_api_url(self.api_url)
        ) as client:
            try:
                result = await client.search(
                    query, num_results=self.num_results, **self.params
                )
                return _format_search_results(result, query)
            except Exception as e:
                logger.warning("AlterLab search failed for %r: %s", query, e)
                return f"Error searching {query!r}: {e}"
