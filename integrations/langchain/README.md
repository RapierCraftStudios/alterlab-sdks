# langchain-alterlab

[![PyPI](https://img.shields.io/pypi/v/langchain-alterlab?logo=pypi&logoColor=white)](https://pypi.org/project/langchain-alterlab/) [![downloads](https://img.shields.io/pypi/dm/langchain-alterlab)](https://pypi.org/project/langchain-alterlab/) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/integrations/langchain)

LangChain integration for the [AlterLab](https://alterlab.io) web scraping API.

## Installation

```bash
pip install langchain-alterlab
```

## Setup

Set your AlterLab API key:

```bash
export ALTERLAB_API_KEY="your-api-key"
```

Get your API key at [alterlab.io/dashboard](https://alterlab.io/dashboard).

## Document Loader

Load web pages as LangChain `Document` objects with structured metadata:

```python
from langchain_alterlab import AlterLabLoader

# Single URL
loader = AlterLabLoader(url="https://example.com/article")
docs = loader.load()

print(docs[0].page_content[:200])
print(docs[0].metadata)
# {'source': 'https://example.com/article', 'title': '...', 'author': '...', ...}
```

### Multiple URLs

```python
loader = AlterLabLoader(
    urls=[
        "https://example.com/page1",
        "https://example.com/page2",
    ],
)
docs = loader.load()
```

### Custom Parameters

```python
loader = AlterLabLoader(
    url="https://example.com",
    params={
        "formats": ["markdown", "json"],
        "mode": "js",  # JavaScript rendering
        "extraction_profile": "article",
    },
)
```

### Async Loading

```python
docs = await loader.aload()
```

## Agent Tool

Use `AlterLabScrapeTool` with LangChain agents to scrape pages on demand:

```python
from langchain_alterlab import AlterLabScrapeTool

tool = AlterLabScrapeTool()

# Direct use
result = tool.invoke("https://example.com")
print(result)
```

### With an Agent

```python
from langchain_openai import ChatOpenAI
from langchain_alterlab import AlterLabScrapeTool

llm = ChatOpenAI()
tools = [AlterLabScrapeTool()]
agent = llm.bind_tools(tools)
```

### With Metadata

```python
tool = AlterLabScrapeTool(include_metadata=True)
result = tool.invoke("https://example.com")
# Output includes title, author, source before content
```

## Metadata Fields

Documents and tool results include structured metadata:

| Field | Description |
|-------|-------------|
| `source` | URL that was scraped |
| `title` | Page title (if detected) |
| `author` | Content author (if detected) |
| `published_at` | Publication date (if detected) |
| `status_code` | HTTP response status code |
| `extraction_method` | How content was extracted |
| `response_time_ms` | API response time |
| `credits_used` | AlterLab credits consumed |
| `tier_used` | Scraping tier (1=curl, 2=http, 3=dynamic, 4=browser) |

## API Reference

See [docs.alterlab.io](https://docs.alterlab.io) for the full AlterLab API documentation.

## Search Tool

Use `AlterLabSearchTool` to let agents run web searches (numbered title, URL and snippet):

```python
from langchain_alterlab import AlterLabSearchTool

tool = AlterLabSearchTool(num_results=5, params={"engine": "google"})
print(tool.invoke("web scraping api"))
```

## Blocked-fetch fallback with unblock-fetch

[`unblock-fetch`](https://pypi.org/project/unblock-fetch/) is a drop-in `requests.get` that falls back
to AlterLab only when the direct fetch is blocked. Wrap it in a tool to keep AlterLab as the fallback:

```python
from langchain_core.tools import tool
from unblock_fetch import get

@tool
def read_page(url: str) -> str:
    """Read a web page; retries through AlterLab only if the direct fetch is blocked."""
    return get(url, timeout=20).text
```

## Links

- Package: [langchain-alterlab on PyPI](https://pypi.org/project/langchain-alterlab/)
- Source: [RapierCraftStudios/alterlab-sdks/integrations/langchain](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/integrations/langchain)
- Documentation: [https://alterlab.io/docs/integrations/langchain](https://alterlab.io/docs/integrations/langchain)
- Issues: [https://github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)
- Get an API key: [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests)
- Security: see the [disclosure policy](https://alterlab.io/security/disclosure) or email [support@alterlab.io](mailto:support@alterlab.io)
