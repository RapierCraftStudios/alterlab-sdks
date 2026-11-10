# crewai-alterlab

[![PyPI](https://img.shields.io/pypi/v/crewai-alterlab?logo=pypi&logoColor=white)](https://pypi.org/project/crewai-alterlab/) [![downloads](https://img.shields.io/pypi/dm/crewai-alterlab)](https://pypi.org/project/crewai-alterlab/) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/integrations/crewai)

CrewAI integration for the [AlterLab](https://alterlab.io) web scraping API.

## Installation

```bash
pip install crewai-alterlab
```

## Setup

Set your AlterLab API key:

```bash
export ALTERLAB_API_KEY="your-api-key"
```

Get your API key at [alterlab.io/dashboard](https://alterlab.io/dashboard).

## Scrape Tool

Scrape individual web pages with `AlterLabScrapeTool`:

```python
from crewai_alterlab import AlterLabScrapeTool

tool = AlterLabScrapeTool()
result = tool.run("https://example.com")
print(result)
```

### With a CrewAI Agent

```python
from crewai import Agent, Task, Crew
from crewai_alterlab import AlterLabScrapeTool

researcher = Agent(
    role="Web Researcher",
    goal="Research topics by scraping web pages",
    backstory="You are an expert web researcher.",
    tools=[AlterLabScrapeTool()],
)

task = Task(
    description="Scrape https://example.com and summarise the content",
    expected_output="A summary of the page content",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task])
result = crew.kickoff()
```

### Custom Parameters

```python
tool = AlterLabScrapeTool(
    scrape_params={
        "formats": ["markdown"],
        "mode": "js",  # JavaScript rendering
    },
)
```

## Crawl Tool

Crawl multiple pages from a website with `AlterLabCrawlTool`:

```python
from crewai_alterlab import AlterLabCrawlTool

tool = AlterLabCrawlTool()
result = tool.run(url="https://docs.example.com", max_pages=5)
print(result)
```

### Research Agent with Both Tools

```python
from crewai import Agent
from crewai_alterlab import AlterLabScrapeTool, AlterLabCrawlTool

researcher = Agent(
    role="Deep Researcher",
    goal="Thoroughly research topics using web data",
    backstory="You gather comprehensive information from the web.",
    tools=[AlterLabScrapeTool(), AlterLabCrawlTool()],
)
```

## API Reference

See [docs.alterlab.io](https://docs.alterlab.io) for the full AlterLab API documentation.

## Search Tool

Run web searches with `AlterLabSearchTool` (numbered title, URL and snippet):

```python
from crewai_alterlab import AlterLabSearchTool

tool = AlterLabSearchTool(num_results=5, search_params={"engine": "google"})
print(tool.run(query="web scraping api"))
```

## Blocked-Fetch Fallback

`BlockedFetchFallbackTool` runs your own fetch first and retries through AlterLab only when
the result is a 403/429, a bot-protection challenge page, a CAPTCHA, or an empty JavaScript
shell. Normal pages, 404s and network errors are returned or raised untouched, so credits are
spent only on blocked fetches:

```python
import requests
from crewai_alterlab import BlockedFetchFallbackTool

tool = BlockedFetchFallbackTool(fetch=lambda url: requests.get(url, timeout=20))
print(tool.run(url="https://example.com"))
```

### Same pattern as a standalone package

[`unblock-fetch`](https://pypi.org/project/unblock-fetch/) is the same fallback as a drop-in
`requests.get` with no CrewAI dependency; the result's `.via` is `direct` or `alterlab`:

```python
from unblock_fetch import get

print(get("https://example.com", timeout=20).text)
```

## Links

- Package: [crewai-alterlab on PyPI](https://pypi.org/project/crewai-alterlab/)
- Source: [RapierCraftStudios/alterlab-sdks/integrations/crewai](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/integrations/crewai)
- Documentation: [https://alterlab.io/docs/integrations/crewai](https://alterlab.io/docs/integrations/crewai)
- Issues: [https://github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)
- Get an API key: [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests)
- Security: see the [disclosure policy](https://alterlab.io/security/disclosure) or email [support@alterlab.io](mailto:support@alterlab.io)
