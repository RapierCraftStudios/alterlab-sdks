"""AlterLab tools for CrewAI agents.

Provides ``AlterLabScrapeTool`` and ``AlterLabCrawlTool`` — CrewAI-compatible
tools that allow agents to scrape and crawl web pages via the AlterLab API.

Usage::

    from crewai_alterlab import AlterLabScrapeTool

    tool = AlterLabScrapeTool()
    # Use with a CrewAI agent
"""

import logging
from typing import Any, Dict, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from crewai_alterlab.utilities import (
    extract_page_content,
    get_api_key,
    get_api_url,
)

logger = logging.getLogger(__name__)


class _ScrapeInput(BaseModel):
    """Input schema for the AlterLab scrape tool."""

    url: str = Field(description="The URL of the web page to scrape.")


class AlterLabScrapeTool(BaseTool):
    """CrewAI tool that scrapes a web page using the AlterLab API.

    Returns the page content as a string (markdown preferred). Designed for
    use with CrewAI agents that need to fetch and read web page content.

    Setup:
        Install the package and set the ``ALTERLAB_API_KEY`` environment
        variable::

            pip install crewai-alterlab
            export ALTERLAB_API_KEY="your-api-key"

    Usage:
        .. code-block:: python

            from crewai_alterlab import AlterLabScrapeTool

            tool = AlterLabScrapeTool()
            result = tool.run("https://example.com")
            print(result)

    With a CrewAI agent:
        .. code-block:: python

            from crewai import Agent
            from crewai_alterlab import AlterLabScrapeTool

            researcher = Agent(
                role="Web Researcher",
                goal="Research topics by scraping web pages",
                tools=[AlterLabScrapeTool()],
            )
    """

    name: str = "AlterLab Scrape"
    description: str = (
        "Scrape a web page and return its content as text. "
        "Input is a URL string. Returns the page content as markdown text. "
        "Useful for reading web pages, articles, documentation, or any "
        "publicly accessible URL."
    )
    args_schema: Type[BaseModel] = _ScrapeInput

    api_key: Optional[str] = None
    """AlterLab API key. Defaults to ALTERLAB_API_KEY env var."""

    api_url: Optional[str] = None
    """AlterLab API base URL. Defaults to https://api.alterlab.io."""

    scrape_params: Dict[str, Any] = Field(default_factory=dict)
    """Additional parameters passed to the AlterLab scrape API."""

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

    def _run(self, url: str) -> str:
        """Scrape a URL and return its content.

        Args:
            url: The URL to scrape.

        Returns:
            Page content as a string, or an error message.
        """
        from alterlab import AlterLabSync

        resolved_key = get_api_key(self.api_key)
        resolved_url = get_api_url(self.api_url)

        client = AlterLabSync(api_key=resolved_key, base_url=resolved_url)
        try:
            result = client.scrape(url, **self.scrape_params)
            content = extract_page_content(result)
            if not content:
                return f"No content could be extracted from {url}"
            return content
        except Exception as e:
            logger.warning("AlterLab scrape failed for %s: %s", url, e)
            return f"Error scraping {url}: {e}"
        finally:
            client.close()


class _CrawlInput(BaseModel):
    """Input schema for the AlterLab crawl tool."""

    url: str = Field(description="The starting URL for the crawl.")
    max_pages: int = Field(
        default=10,
        description="Maximum number of pages to crawl.",
    )


class AlterLabCrawlTool(BaseTool):
    """CrewAI tool that crawls a website using the AlterLab API.

    Crawls multiple pages starting from a URL and returns their combined
    content. Useful for gathering comprehensive information from a website.

    Setup:
        Install the package and set the ``ALTERLAB_API_KEY`` environment
        variable::

            pip install crewai-alterlab
            export ALTERLAB_API_KEY="your-api-key"

    Usage:
        .. code-block:: python

            from crewai_alterlab import AlterLabCrawlTool

            tool = AlterLabCrawlTool()
            result = tool.run(url="https://docs.example.com", max_pages=5)
            print(result)
    """

    name: str = "AlterLab Crawl"
    description: str = (
        "Crawl a website starting from a URL and return content from "
        "multiple pages. Input requires a URL and optional max_pages "
        "(default 10). Useful for gathering comprehensive information "
        "from documentation sites, blogs, or multi-page resources."
    )
    args_schema: Type[BaseModel] = _CrawlInput

    api_key: Optional[str] = None
    """AlterLab API key. Defaults to ALTERLAB_API_KEY env var."""

    api_url: Optional[str] = None
    """AlterLab API base URL. Defaults to https://api.alterlab.io."""

    poll_timeout: float = 300.0
    """Maximum seconds to wait for the crawl to complete."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise AlterLabCrawlTool.

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
        get_api_key(self.api_key)

    def _run(self, url: str, max_pages: int = 10) -> str:
        """Crawl a website and return combined content.

        Args:
            url: The starting URL for the crawl.
            max_pages: Maximum number of pages to crawl.

        Returns:
            Combined page content as a string, or an error message.
        """
        from alterlab import AlterLabSync

        resolved_key = get_api_key(self.api_key)
        resolved_url = get_api_url(self.api_url)

        client = AlterLabSync(api_key=resolved_key, base_url=resolved_url)
        try:
            result = client.crawl_and_wait(
                url,
                max_pages=max_pages,
                formats=["markdown"],
                poll_timeout=self.poll_timeout,
            )

            pages = result.get("pages", [])
            if not pages:
                if result.get("status") == "failed":
                    return (
                        f"Crawl of {url} failed: {result.get('error', 'unknown error')}"
                    )
                return f"No pages could be crawled from {url}"

            parts = []
            for page in pages:
                page_url = page.get("url", "unknown")
                content = extract_page_content(page)
                if content:
                    parts.append(f"## {page_url}\n\n{content}")

            if not parts:
                return f"No content could be extracted from crawled pages at {url}"

            return "\n\n---\n\n".join(parts)
        except Exception as e:
            logger.warning("AlterLab crawl failed for %s: %s", url, e)
            return f"Error crawling {url}: {e}"
        finally:
            client.close()


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
    """CrewAI tool that runs a web search using the AlterLab Search API.

    Returns numbered results (title, URL, snippet) as a string.

    Usage:
        .. code-block:: python

            from crewai_alterlab import AlterLabSearchTool

            tool = AlterLabSearchTool(num_results=5)
            print(tool.run(query="web scraping api"))
    """

    name: str = "AlterLab Search"
    description: str = (
        "Search the web and return a numbered list of results with title, "
        "URL and snippet. Input is a search query string."
    )
    args_schema: Type[BaseModel] = _SearchInput

    api_key: Optional[str] = None
    """AlterLab API key. Defaults to ALTERLAB_API_KEY env var."""

    api_url: Optional[str] = None
    """AlterLab API base URL. Defaults to https://api.alterlab.io."""

    num_results: int = 10
    """Number of results to return (1-30)."""

    search_params: Dict[str, Any] = Field(default_factory=dict)
    """Additional parameters passed to the AlterLab search API (e.g. engine, domain)."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise AlterLabSearchTool.

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
        get_api_key(self.api_key)

    def _run(self, query: str) -> str:
        """Search the web and return formatted results, or an error message."""
        from alterlab import AlterLabSync

        client = AlterLabSync(
            api_key=get_api_key(self.api_key), base_url=get_api_url(self.api_url)
        )
        try:
            result = client.search(
                query, num_results=self.num_results, **self.search_params
            )
            return _format_search_results(result, query)
        except Exception as e:
            logger.warning("AlterLab search failed for %r: %s", query, e)
            return f"Error searching {query!r}: {e}"
        finally:
            client.close()
