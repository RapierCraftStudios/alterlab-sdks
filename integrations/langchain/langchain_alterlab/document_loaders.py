"""AlterLab document loader for LangChain.

Scrapes web pages via the AlterLab API and returns them as LangChain
``Document`` objects with structured metadata.

Setup::

    pip install langchain-alterlab
    export ALTERLAB_API_KEY="your-api-key"

Usage::

    from langchain_alterlab import AlterLabLoader

    loader = AlterLabLoader(url="https://example.com/article")
    docs = loader.load()
    print(docs[0].page_content[:200])
    print(docs[0].metadata)
"""

import logging
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

from langchain_alterlab.utilities import (
    build_metadata,
    extract_page_content,
    get_api_key,
    get_api_url,
)

logger = logging.getLogger(__name__)


class AlterLabLoader(BaseLoader):
    """Load web pages using the AlterLab scraping API.

    AlterLab returns structured data with typed metadata (title, author,
    published date, content type) and supports multiple output formats
    optimised for LLM consumption.

    Setup:
        Install the package and set the ``ALTERLAB_API_KEY`` environment
        variable::

            pip install langchain-alterlab
            export ALTERLAB_API_KEY="your-api-key"

    Instantiate:
        .. code-block:: python

            from langchain_alterlab import AlterLabLoader

            # Single URL
            loader = AlterLabLoader(url="https://example.com/article")

            # Multiple URLs
            loader = AlterLabLoader(
                urls=[
                    "https://example.com/page1",
                    "https://example.com/page2",
                ],
            )

            # With custom parameters
            loader = AlterLabLoader(
                url="https://example.com",
                params={
                    "formats": ["markdown", "json"],
                    "extraction_profile": "article",
                },
            )

    Lazy load:
        .. code-block:: python

            for doc in loader.lazy_load():
                print(doc.page_content[:100])
                print(doc.metadata)

    Async load:
        .. code-block:: python

            docs = await loader.aload()

    Metadata fields:
        - ``source``: The URL that was scraped
        - ``title``: Page title (if detected)
        - ``author``: Content author (if detected)
        - ``published_at``: Publication date (if detected)
        - ``status_code``: HTTP response status code
        - ``extraction_method``: How content was extracted
        - ``response_time_ms``: API response time in milliseconds
        - ``credits_used``: AlterLab credits consumed
        - ``tier_used``: Scraping tier used (1=curl, 2=http, 3=dynamic, 4=browser)

    See https://docs.alterlab.io for full API documentation.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        urls: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise AlterLabLoader.

        Args:
            url: Single URL to scrape.
            urls: List of URLs to scrape. Cannot be used with ``url``.
            api_key: AlterLab API key. Defaults to ``ALTERLAB_API_KEY``
                environment variable.
            api_url: AlterLab API base URL. Defaults to ``ALTERLAB_API_URL``
                environment variable or ``https://api.alterlab.io``.
            params: Additional parameters passed to the AlterLab scrape API.
                Common parameters include ``formats``, ``mode``,
                ``extraction_profile``, ``extraction_schema``, ``advanced``,
                and ``cost_controls``.

        Raises:
            ImportError: If the ``alterlab`` package is not installed.
            ValueError: If neither ``url`` nor ``urls`` is provided, or both.
        """
        try:
            import alterlab  # noqa: F401
        except ImportError:
            raise ImportError(
                "Could not import alterlab python package. "
                "Please install it with `pip install alterlab`."
            )

        if url and urls:
            raise ValueError("Provide either 'url' or 'urls', not both.")
        if not url and not urls:
            raise ValueError("Either 'url' or 'urls' must be provided.")

        self.api_key = get_api_key(api_key)
        self.api_url = get_api_url(api_url)
        self.urls: List[str] = urls if urls else [url]  # type: ignore[list-item]
        self.params = params or {}

    def lazy_load(self) -> Iterator[Document]:
        """Load documents from the AlterLab API synchronously.

        Yields:
            Document objects with page content and structured metadata.
        """
        from alterlab import AlterLabSync

        client = AlterLabSync(api_key=self.api_key, base_url=self.api_url)
        try:
            for url in self.urls:
                try:
                    result = client.scrape(url, **self.params)
                    doc = self._result_to_document(result, url)
                    if doc:
                        yield doc
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", url, e)
                    continue
        finally:
            client.close()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """Load documents from the AlterLab API asynchronously.

        Yields:
            Document objects with page content and structured metadata.
        """
        from alterlab import AlterLab

        async with AlterLab(api_key=self.api_key, base_url=self.api_url) as client:
            for url in self.urls:
                try:
                    result = await client.scrape(url, **self.params)
                    doc = self._result_to_document(result, url)
                    if doc:
                        yield doc
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", url, e)
                    continue

    @staticmethod
    def _result_to_document(
        result: Dict[str, Any], source_url: str
    ) -> Optional[Document]:
        """Convert an AlterLab API response to a LangChain Document.

        Args:
            result: AlterLab API response dictionary.
            source_url: The URL that was scraped.

        Returns:
            A Document with page_content and metadata, or ``None`` if no
            content was extracted.
        """
        page_content = extract_page_content(result)
        if not page_content:
            return None

        metadata = build_metadata(result, source_url)
        return Document(page_content=page_content, metadata=metadata)
