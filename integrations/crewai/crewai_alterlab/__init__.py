"""CrewAI integration for the AlterLab web scraping API.

Provides:
- ``AlterLabScrapeTool``: Tool for CrewAI agents to scrape individual web pages.
- ``AlterLabCrawlTool``: Tool for CrewAI agents to crawl websites.
- ``AlterLabSearchTool``: Tool for CrewAI agents to run web searches.

Install::

    pip install crewai-alterlab

Quick start::

    from crewai_alterlab import AlterLabScrapeTool

    tool = AlterLabScrapeTool()
    result = tool.run("https://example.com")
    print(result)
"""

from crewai_alterlab.fallback import AlterLabFallbackTool as BlockedFetchFallbackTool
from crewai_alterlab.tools import (
    AlterLabCrawlTool,
    AlterLabScrapeTool,
    AlterLabSearchTool,
)

__version__ = "0.1.2"
__all__ = [
    "BlockedFetchFallbackTool",
    "AlterLabScrapeTool",
    "AlterLabCrawlTool",
    "AlterLabSearchTool",
]
