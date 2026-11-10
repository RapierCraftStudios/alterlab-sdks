# llama-index-readers-alterlab

[![PyPI](https://img.shields.io/pypi/v/llama-index-readers-alterlab?logo=pypi&logoColor=white)](https://pypi.org/project/llama-index-readers-alterlab/) [![downloads](https://img.shields.io/pypi/dm/llama-index-readers-alterlab)](https://pypi.org/project/llama-index-readers-alterlab/) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/integrations/llama-index)

Official [AlterLab](https://alterlab.io) data reader for [LlamaIndex](https://www.llamaindex.ai/).

Scrape any web page — including JavaScript-heavy SPAs and pages that need full browser rendering — and load
the results directly into LlamaIndex Documents for RAG pipelines.

## Installation

```bash
pip install llama-index-readers-alterlab
```

## Quick Start

```python
from llama_index.readers.alterlab import AlterLabReader

reader = AlterLabReader(api_key="sk_live_...")

# Load one page
docs = reader.load_data(["https://example.com/docs"])
print(docs[0].text)

# Load multiple pages
docs = reader.load_data([
    "https://docs.stripe.com/api/charges",
    "https://docs.stripe.com/api/customers",
])
```

## RAG Pipeline

```python
from llama_index.core import VectorStoreIndex, Settings
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.readers.alterlab import AlterLabReader

Settings.llm = OpenAI(model="gpt-4o-mini")
Settings.embed_model = OpenAIEmbedding()

reader = AlterLabReader(api_key="sk_live_...")
docs = reader.load_data([
    "https://docs.stripe.com/api/charges",
    "https://docs.stripe.com/api/refunds",
])

index = VectorStoreIndex.from_documents(docs)
engine = index.as_query_engine(similarity_top_k=3)
print(engine.query("How do I create a refund?"))
```

## Cleanup

`AlterLabReader` holds a persistent `AlterLabSync` client (and its `asyncio` event loop) for
its lifetime. Use it as a context manager so the client is closed automatically:

```python
from llama_index.readers.alterlab import AlterLabReader

with AlterLabReader(api_key="sk_live_...") as reader:
    docs = reader.load_data(["https://example.com/docs"])
    print(docs[0].text)
```

If you can't use a `with` block, call `close()` explicitly when you're done with the reader:

```python
reader = AlterLabReader(api_key="sk_live_...")
docs = reader.load_data(["https://example.com/docs"])
reader.close()
```

`close()` is idempotent — calling it again (including after a `with` block already closed the
reader) is a no-op.

## Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str` | required | AlterLab API key |
| `mode` | `str` | `"auto"` | Scraping mode: `auto`, `html`, `js`, `pdf`, `ocr` |
| `output_format` | `str` | `"markdown"` | Content format: `markdown`, `text`, `html`, `rag`, `content` |
| `render_js` | `bool` | `False` | Enable JavaScript rendering (browser tier) |
| `base_url` | `str` | `"https://api.alterlab.io"` | API base URL |

`load_data(urls, mode=None, output_format=None, extra_info=None, **kwargs)` accepts the same parameters plus any keyword arguments forwarded to `AlterLabSync.scrape()`.

## Links

- [AlterLab Docs](https://alterlab.io/docs)
- [LlamaIndex Integration Guide](https://alterlab.io/docs/integrations/llamaindex)
- [AlterLab Python SDK](https://pypi.org/project/alterlab/)

## Search Tool

`AlterLabSearchTool` runs web searches and returns numbered title, URL and snippet text:

```python
from llama_index.readers.alterlab import AlterLabSearchTool

tool = AlterLabSearchTool(api_key="sk_live_...", num_results=5, engine="google")
function_tool = tool.to_tool()  # use with a LlamaIndex agent
```

## Blocked-Fetch Fallback

`AlterLabBlockedFetchFallback` runs your own fetch first and retries through AlterLab only when
the result is a 403/429, a bot-protection challenge page, a CAPTCHA, or an empty JavaScript
shell. Normal pages, 404s and network errors are returned or raised untouched:

```python
import requests
from llama_index.readers.alterlab import AlterLabBlockedFetchFallback

fallback = AlterLabBlockedFetchFallback(fetch=lambda url: requests.get(url, timeout=20))
function_tool = fallback.to_tool()  # use with a LlamaIndex agent
```
