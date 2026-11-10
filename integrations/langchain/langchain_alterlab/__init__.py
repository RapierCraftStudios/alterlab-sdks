"""LangChain integration for the AlterLab web scraping API.

Provides:
- ``AlterLabLoader``: Document loader for scraping web pages into LangChain Documents.
- ``AlterLabScrapeTool``: Tool for LangChain agents to scrape web pages on demand.
- ``AlterLabSearchTool``: Tool for LangChain agents to run web searches.
- ``BlockedFetchFallback``: Tool that tries your fetch and retries via AlterLab only when it is blocked.

Install::

    pip install langchain-alterlab

Quick start::

    from langchain_alterlab import AlterLabLoader

    loader = AlterLabLoader(url="https://example.com")
    docs = loader.load()
    print(docs[0].page_content[:200])
"""

from langchain_alterlab.document_loaders import AlterLabLoader
from langchain_alterlab.fallback import BlockedFetchFallbackTool as BlockedFetchFallback
from langchain_alterlab.tools import AlterLabScrapeTool, AlterLabSearchTool

__version__ = "0.1.1"
__all__ = [
    "AlterLabLoader",
    "AlterLabScrapeTool",
    "AlterLabSearchTool",
    "BlockedFetchFallback",
]
