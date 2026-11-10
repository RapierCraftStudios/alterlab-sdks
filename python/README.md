# AlterLab Python SDK

[![PyPI](https://img.shields.io/pypi/v/alterlab?logo=pypi&logoColor=white)](https://pypi.org/project/alterlab/) [![downloads](https://img.shields.io/pypi/dm/alterlab)](https://pypi.org/project/alterlab/) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/python)

Official Python client for [AlterLab](https://alterlab.io): search, read and extract the live web, with automatic fallback from direct fetch to full browser rendering. Pay only for successful requests.

## Installation

```bash
pip install alterlab
```

## Quick Start

```python
import asyncio
from alterlab import AlterLab

async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        result = await client.scrape("https://example.com")
        print(result["content"])

asyncio.run(main())
```

Output (the page text for `https://example.com`):

```text
Example Domain

This domain is for use in documentation examples without needing permission. Avoid use in operations.
```

See [pricing](https://alterlab.io/pricing) and the [benchmark](https://alterlab.io/benchmark).

Prefer synchronous code? Use the sync wrapper:

```python
from alterlab import AlterLabSync

with AlterLabSync(api_key="sk_test_...") as client:
    result = client.scrape("https://example.com")
    print(result["content"])
```

### Drop-in `requests` replacement

Already have code written against the [`requests`](https://requests.readthedocs.io/)
library? Swap the import line and keep the rest of your code unchanged — every call is
routed through AlterLab, with automatic fallback from direct fetch to full browser
rendering, instead of a bare socket connection, with no new backend endpoint involved.

```python
from alterlab import requests  # instead of: import requests

# Reads ALTERLAB_API_KEY from the environment on first call.
response = requests.get("https://example.com", headers={"X-Custom-Header": "value"})
print(response.status_code)
print(response.text)

data = requests.post(
    "https://api.example.com/thing",
    json={"key": "value"},
).json()
```

No `ALTERLAB_API_KEY` in your environment, or want to set the key explicitly?

```python
from alterlab import requests

requests.configure(api_key="sk_test_...")
response = requests.get("https://example.com")
```

Supported: `requests.get`, `.post`, `.put`, `.patch`, `.delete`, `.request(method, url, ...)`,
with `params=`, `json=`, `data=`, `headers=`, and `timeout=` matching `requests`' own call
signature. The returned `Response` object exposes `.status_code`, `.text`, `.content`,
`.headers`, `.url`, `.json()`, `.ok`, and `.raise_for_status()`.

**Note**: AlterLab's own exceptions (`AlterLabAPIError` and subclasses like
`AuthenticationError`, `InsufficientFundsError`, `RateLimitError`) propagate directly from
these calls rather than being wrapped in `requests.exceptions` types — catch
`alterlab.AlterLabAPIError` instead of `requests.exceptions.HTTPError`. This includes
`.raise_for_status()`: for a 4xx/5xx status returned by the *target site* through an
otherwise-successful scrape, it raises `alterlab.AlterLabHTTPError` (a subclass of
`AlterLabAPIError`, with a `.status_code` attribute) — not `requests.exceptions.HTTPError`.

## Command line

The `alterlab` CLI ships with the SDK (MIT licensed). Install it with `pipx install alterlab`,
`uvx alterlab ...` or `pip install alterlab` (add `keyring` to store the key in the OS keychain).

```bash
alterlab login --email you@example.com   # a human approves in the browser; the key is never printed
alterlab scrape https://example.com -f md --estimate
alterlab crawl https://example.com --max 50 --max-cost 0.50 | jq .url
cat urls.txt | alterlab batch
alterlab search "web scraping" --content
alterlab extract https://shop.example/item --profile product
alterlab fetch https://example.com       # direct fetch first, AlterLab only if blocked
```

Data commands stream NDJSON (or markdown) to stdout and print the cost to stderr.
`--estimate` prints the quote and exits; `--max-cost USD` is a hard cap.

No account needed: `alterlab detect <url>`, `alterlab doctor <url>`, `alterlab md <file|url>`,
`alterlab robots <url>`.

Agents: `claude mcp add alterlab -- uvx alterlab mcp` runs a local stdio MCP server;
`alterlab skill install` installs the agent skill.

`alterlab routing-policy [--agent claude|codex|agents|cursor|copilot|windsurf] [--domains a.com,b.org] [--dir PATH]` writes the "use AlterLab for web tasks" policy into the client's project instructions file (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/alterlab.mdc`, ...). Re-running replaces the marked block in place; all other content is kept.

## Methods

### `scrape(url, **kwargs)`

Scrape a single URL. Supports all scraping modes and automatic async job polling.

Sync downgrades are followed automatically: if a synchronous `scrape()` outruns the sync window and the API answers `202` with `sync_downgraded`, the SDK polls the job and returns the real result. Only `sync=False` returns the raw job envelope; a poll timeout raises `alterlab.client.JobTimeoutError` (with `job_id` and `poll_url`).

```python
# Simple HTML scraping
result = await client.scrape("https://example.com")

# JavaScript rendering
result = await client.scrape("https://example.com", mode="js")

# With output formats
result = await client.scrape(
    "https://example.com",
    formats=["markdown", "text"],
)

# Structured extraction with a profile
result = await client.scrape(
    "https://example.com/product",
    extraction_profile="product",
)

# Structured extraction with a JSON schema
result = await client.scrape(
    "https://example.com/product",
    extraction_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "price": {"type": "number"},
        },
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | URL to scrape |
| `mode` | `str` | `"auto"` | Scraping mode: `auto`, `html`, `js`, `pdf`, `ocr` |
| `sync` | `bool` | `True` | Wait for result (False returns job_id immediately) |
| `response` | `Optional[Literal["full", "minimal"]]` | `None` | `"minimal"` returns only content, status, url, cost and warnings (server default for MCP, agent and keyless keys) |
| `sync_policy` | `Literal["auto", "wait_until_deadline"]` | `"auto"` | `auto` preserves early 202 handoffs; `wait_until_deadline` waits through tier boundaries until terminal completion or the server's 85-second safe deadline (requires `sync=True`) |
| `formats` | `list` | `None` | Output formats: `text`, `json`, `json_v2`, `html`, `markdown`, `rag` |
| `extraction_schema` | `dict` | `None` | JSON Schema for structured extraction |
| `extraction_prompt` | `str` | `None` | Natural language extraction instructions |
| `extraction_profile` | `str` | `None` | Pre-built profile: `auto`, `product`, `article`, `job_posting`, `faq`, `recipe`, `event` |
| `advanced` | `AdvancedOptions` | `None` | Advanced scraping options (see below) |
| `cost_controls` | `CostControls` | `None` | Cost control parameters (see below) |
| `force_refresh` | `bool` | `False` | Bypass cache |
| `evidence` | `bool` | `False` | Include provenance for extracted fields |

### `crawl(url, **kwargs)`

Start a multi-page website crawl. Returns immediately with a `crawl_id` for polling.

```python
crawl = await client.crawl(
    "https://example.com",
    max_pages=200,
    max_depth=2,
    include_patterns=["/blog/*"],
    formats=["markdown"],
)
print(f"Crawl ID: {crawl['crawl_id']}")
print(f"Estimated pages: {crawl['estimated_pages']}")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | Starting URL |
| `max_pages` | `int` | `50` | Maximum pages to scrape (1-100,000) |
| `max_depth` | `int` | `3` | Maximum link-following depth (0-50) |
| `include_patterns` | `list[str]` | `None` | Glob patterns to include (e.g. `["/products/*"]`) |
| `exclude_patterns` | `list[str]` | `None` | Glob patterns to exclude |
| `formats` | `list` | `None` | Output formats per page |
| `extraction_schema` | `dict` | `None` | JSON Schema for extraction on each page |
| `extraction_profile` | `str` | `None` | Extraction profile for each page |
| `webhook_url` | `str` | `None` | URL for `crawl.completed` webhook |
| `respect_robots` | `bool` | `True` | Respect robots.txt |
| `include_subdomains` | `bool` | `False` | Follow links to subdomains |
| `cost_controls` | `dict` | `None` | `{"max_credits": N, "max_tier": "2"}` |

### `crawl_and_wait(url, **kwargs)`

Start a crawl and poll until completion. Returns all page results.

```python
results = await client.crawl_and_wait(
    "https://example.com",
    max_pages=50,
    formats=["markdown"],
    poll_timeout=300.0,
)
print(f"Status: {results['status']}")
print(f"Pages scraped: {results['completed']}")
for page in results.get("pages", []):
    print(f"  {page['url']}: {page['status']}")
```

### `get_crawl(crawl_id, include_results=False)`

Check crawl progress. Pass `include_results=True` to get per-page scrape results.

```python
status = await client.get_crawl(crawl_id)
print(f"{status['completed']}/{status['total']} pages done")
```

### `cancel_crawl(crawl_id)`

Cancel a running crawl. Credits for unprocessed pages are refunded.

```python
result = await client.cancel_crawl(crawl_id)
print(f"Refunded {result['credits_refunded']} credits")
```

### `batch_scrape(requests, webhook_url=None)`

Submit multiple scrape requests as a batch.

```python
batch = await client.batch_scrape([
    {"url": "https://example.com/page1", "mode": "html"},
    {"url": "https://example.com/page2", "mode": "js"},
])
for job_id in batch["job_ids"]:
    result = await client.wait_for_job(job_id)
```

### `search(query, **kwargs)`

Unified, vendor-neutral search with page content by default. A plain `search("query")` runs
`engine="auto"` on `/v1/search` and returns each result page as concise markdown with a
per-result `content_status` (`scrape_results=True`, `concise=True`, `mode="standard"`). The unified
query is a flat $0.001; each fetched page bills at its fetch tier. Pass `scrape_results=False` for the
result list only. The SDK default engine is `auto`; the REST API's own default stays `duckduckgo`. An explicit `engine` keeps that engine's behaviour (no content unless asked for,
plain requests use `/v1/serp`).

```python
results = client.search("headless browsers")  # unified, with content
for item in results["results"]:
    print(item["rank"], item["title"], item["url"], item["content_status"])

serp = client.search("headless browsers", engine="google", num=10, start=0, device="desktop")
for item in serp["organic_results"]:
    print(item["position"], item["title"], item["url"])
```

| Engine | Price per query |
| --- | --- |
| `duckduckgo` | $0.001 |
| `google` | $0.004 |
| `bing` | $0.004 |

With `scrape_results`, pass `sync=True` to wait up to ~30s and get content in one call; on timeout the
response is a 202 with `next_action` (poll the search id).

`scrape_results`, `domain` and `time_range` are still served by the `/v1/search` alias, so
requests that use them are sent there. The response is the JSON of the endpoint used: `organic_results` from
`/v1/serp`, `results` from the alias. See the
[migration guide](https://alterlab.io/docs/migrations/search-to-serp).

### `research(query, **options)` and the research job methods

Budgeted deep research on your own model key (BYOK; a missing key returns `byok_key_required`
and charges nothing). Every claim in the result carries citations.

```python
job = await client.research(
    "Which EU countries ban fur farming?",
    effort="standard",
    max_cost_microcents=50_000,
    output="both",
)
job = await client.wait_for_research(job["id"])  # returns on completed / completed_partial / failed / cancelled
print(job["status"], job["cost"], job["result"])
```

Also: `get_research(id)`, `cancel_research(id)`, `research_events(id, last_event_id=None)`
(progress events, resumable), and for `plan_first=True` jobs `get_research_plan(id)`,
`update_research_plan(id, plan)` and `approve_research(id, plan=None)`. Every method has a sync
twin on `AlterLabSync`. See the [API reference](https://alterlab.io/docs/api/research).

### `batch_search(queries, **kwargs)` and `get_batch_search(batch_id)`

Submit and poll a batch of search queries. Each query is billed at the engine rate above.

### `feedback(category, tried, happened, expected=None, job_id=None)`

Tell AlterLab what was hard. Returns `cluster_key` and `status_url`. Never include customer data.

```python
result = client.feedback("blocked", "mode=auto", "empty body with 200", job_id="job_123")
print(result["cluster_key"], result["status_url"])
```

CLI (reads `ALTERLAB_API_KEY`; `--job-id` defaults to `$ALTERLAB_LAST_JOB_ID`):

```bash
alterlab feedback --category blocked --message "empty body with 200" --job-id job_123
```

### `estimate_cost(url, **kwargs)`

Get a cost estimate before scraping.

```python
estimate = await client.estimate_cost("https://example.com", mode="js")
print(f"Estimated: {estimate['estimated_credits']} credits")
print(f"Max possible: {estimate['max_possible_credits']} credits")
```

### `get_usage()`

Check your balance and usage stats. All monetary values are in **microcents** (1,000,000 = $1.00).

```python
usage = await client.get_usage()
balance = usage['balance_microcents'] / 1_000_000
print(f"Balance: ${balance:.4f}")
print(f"Account tier: {usage['account_tier']}")
print(f"Entitlement source: {usage['entitlement_source']}")
print(f"Used this month: ${usage['credits_used_month'] / 1_000_000:.4f}")
print(f"Period: {usage['period_start']} to {usage['period_end']}")
```

### `wait_for_job(job_id, **kwargs)`

Poll an async job until completion with exponential backoff.

```python
# Start async scrape
response = await client.scrape("https://example.com", sync=False)
result = await client.wait_for_job(response["job_id"])
```

### `get_job_status(job_id, wait=0)`

Check job status. Returns immediately by default; pass `wait` (seconds, `>= 0`) to
have the server hold the request until the job finishes or the window elapses.

```python
status = await client.get_job_status(job_id)
print(f"Status: {status['status']}")

# Long-poll for up to 20 seconds
status = await client.get_job_status(job_id, wait=20)
```

## Configuration

### `AdvancedOptions`

Fine-grained control over scraping behavior with credit cost implications.

```python
from alterlab import AdvancedOptions

advanced = AdvancedOptions(
    render_js=True,       # +3 credits — headless browser rendering
    screenshot=True,      # +1 credit — full-page screenshot (requires render_js)
    markdown=True,        # Free — convert to markdown
    generate_pdf=True,    # +2 credits — generate PDF (requires render_js)
    ocr=True,             # +5 credits — extract text from images
    use_proxy=True,       # +1 credit — premium proxy
    wait_condition="networkidle",  # domcontentloaded | networkidle | load
)

result = await client.scrape("https://example.com", advanced=advanced)
```

### `CostControls`

Set spending limits and optimization preferences.

```python
from alterlab import CostControls

controls = CostControls(
    max_credits=5,     # Hard credit limit for this request
    max_tier="2",      # Don't escalate beyond tier 2
    prefer_cost=True,  # Optimize for lowest cost
    prefer_speed=True, # Optimize for fastest response
    fail_fast=True,    # Fail immediately if limits would be exceeded
    fallback_on_block=False,  # Opt-in: if a forced browser render hits a verification screen or timeout, retry once at T3/T3.5
)

result = await client.scrape("https://example.com", cost_controls=controls)
```

## Browser actions

Run a sequence of browser actions after page load (max 20, requires `render_js=True`).
Build them with the typed `Actions` helpers; constraint violations raise `ValueError`
before the request is sent. Raw dicts such as `{"type": "click", "selector": "..."}`
are still accepted.

```python
from alterlab import Actions, AdvancedOptions

# Screenshot after actions: click, wait, then capture the resulting page
result = await client.scrape(
    "https://example.com/products",
    advanced=AdvancedOptions(render_js=True),
    actions=[
        Actions.dismiss_consent(),
        Actions.click("button.load-more"),
        Actions.wait(milliseconds=1000),
        Actions.evaluate("document.title"),
        Actions.screenshot(full_page=True),
    ],
)

for ar in result["action_results"] or []:
    # Each entry is an ActionResult: a dict with typed attribute access
    print(ar.index, ar.type, ar.success, ar.error)

title = result["action_results"][3].result
screenshot_url = result["action_results"][4].screenshot_url
```

Available builders: `wait`, `wait_for`, `click`, `fill`, `press`, `scroll`,
`infinite_scroll`, `screenshot`, `evaluate`, `dismiss_consent`. Failed actions are
skipped; check `ar.success` and `ar.error` on each result.

### Downloading files

`Actions.download(selector=... | url=...)` captures a file download started by the
page (exactly one of `selector` or `url`; `timeout_ms` 1000-30000, optional
`max_bytes` up to 100 MiB, `frame` only with `selector`; at most 5 per request).
The file is stored privately and the matching action result carries
`ActionResult.artifact` metadata (`artifact_id`, `filename`, `media_type`,
`size_bytes`, `sha256`, `scan_status`, `expires_at`).

Multi-file: `max_files` (1-10) collects several files into
`ActionResult.artifacts`; `max_total_bytes` caps their total size, `quiet_ms`
(100-10000) ends collection after an idle period and `bundle="zip"` also stores
a ZIP, returned as `ActionResult.bundle` (the last three need `max_files > 1`).

```python
result = client.scrape(
    "https://example.com/reports",
    advanced=AdvancedOptions(render_js=True),
    actions=[Actions.click("#export"), Actions.download(selector="a.csv")],
)
artifact = result["action_results"][1].artifact
client.get_artifact(artifact.artifact_id)             # metadata
client.get_artifact_url(artifact.artifact_id)["url"]  # short-lived signed URL
client.download_artifact(artifact.artifact_id, "report.csv")  # saves the file
```

The same methods exist on `AlterLab` (awaitable) and `AlterLabSync`, and as
`alterlab.artifacts.get_artifact(client, id)` etc. The download is fetched
without your API key and written atomically (a failed download leaves no file).

## Convenience Methods

```python
# HTML only (fastest, 1 credit base)
result = await client.scrape_html("https://example.com")

# JavaScript rendering
result = await client.scrape_js("https://example.com", screenshot=True)

# PDF extraction
result = await client.scrape_pdf("https://example.com/doc.pdf")

# OCR
result = await client.scrape_ocr("https://example.com/image.png", language="eng")
```

## Error Handling

```python
from alterlab import (
    AlterLabAPIError,
    AlterLabTimeoutError,
    AlterLabError,
    AuthenticationError,
    InsufficientFundsError,
    RateLimitError,
)

try:
    result = await client.scrape("https://example.com")
except AuthenticationError:
    print("Check your API key at https://alterlab.io/dashboard/keys")
except InsufficientFundsError as e:
    print(f"Add funds at: {e.billing_url}")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except AlterLabAPIError as e:
    print(f"API error {e.status_code}: {e.detail}")
except AlterLabTimeoutError as e:
    print(f"Job timed out: {e}")
except AlterLabError as e:
    print(f"SDK error: {e}")
```

| Exception | When |
|-----------|------|
| `AuthenticationError` | HTTP 401 — invalid or missing API key |
| `InsufficientFundsError` | HTTP 402 — insufficient balance (has `.billing_url`) |
| `RateLimitError` | HTTP 429 after retries exhausted or `max_retry_wait` reached (has `.retry_after`, `.scope`, `.limit`, `.account_tier`, `.docs_url`, `.rate_limit_*`, `.hint`; `None` for edge 429s without the canonical body). For `.error_code == "repeat_failure_backoff"` (the same request failed the same way several times in a row; no credits charged) it also has `.consecutive_failures`, `.outcome_class` and `.failure_code`: retry after `.retry_after`, with different request options, or with `force_refresh=True` |
| `AlterLabAPIError` | Other HTTP 4xx/5xx from the API (has `.status_code`, `.detail` and `.hint`) |
| `JobFailedError` | Polled job ended `failed`, `rejected` or `cancelled` (has `.job_id`, `.status`, `.hint`) |
| `AlterLabTimeoutError` | Async job polling exceeded timeout |
| `AlterLabValidationError` | Invalid parameters (e.g. `screenshot=True` without `render_js`) |
| `JobExpiredError` | Job result expired (1-hour TTL) — resubmit the request |
| `AlterLabHTTPError` | `requests`-compat `.raise_for_status()` — 4xx/5xx from the *target site*, not the API (has `.status_code`) |
| `AlterLabError` | Base class for all SDK errors |

All typed exceptions (`AuthenticationError`, `InsufficientFundsError`, `RateLimitError`,
`AlterLabHTTPError`) are subclasses of `AlterLabAPIError` — existing `except AlterLabAPIError`
blocks still catch them.

### Retry hints

When a request forces browser rendering (`render_js=True` or `force_tier="4"`) and the page
returns a verification screen or does not finish loading in time, the error carries a `hint`
(`{"code": "render_js_auto", "reason": "challenge" | "timeout", "message": ...}`). It is on
`AlterLabAPIError.hint` (failed sync scrape), `JobFailedError.hint` (failed polled job), and in
a failed crawl page's `error`. `get_error_hint()` reads any of them:

```python
from alterlab import AdvancedOptions, AlterLabAPIError, get_error_hint

try:
    result = await client.scrape(
        "https://example.com", advanced=AdvancedOptions(render_js=True)
    )
except AlterLabAPIError as e:
    hint = get_error_hint(e)
    if hint and hint["code"] == "render_js_auto":
        print(hint["message"])
        result = await client.scrape(
            "https://example.com", advanced=AdvancedOptions(render_js="auto")
        )
```

For pages that only sometimes need a browser, prefer `render_js="auto"` from the start. Keep
`render_js=True` for `screenshot`, `generate_pdf` and browser `actions`.

## Client Options

```python
client = AlterLab(
    api_key="sk_test_...",                  # Optional — falls back to ALTERLAB_API_KEY env var
    base_url="https://api.alterlab.io",     # Default API URL
    timeout=30,                              # Request timeout (seconds)
    max_retries=3,                           # Retry count for transient failures
    retry_delay=1.0,                         # Initial retry delay (jittered exponential backoff)
    max_retry_wait=60.0,                     # Max total seconds spent waiting between retries (None = no cap)
)
```

429 and 5xx responses are retried with jittered exponential backoff. A `Retry-After` header
is honoured as a minimum wait; if waiting it out would exceed `max_retry_wait`, the
`RateLimitError` is raised immediately with `.retry_after` set so you can schedule the retry.

If `api_key` is omitted, the client reads it from the `ALTERLAB_API_KEY` environment variable:

```python
# With ALTERLAB_API_KEY set in the environment
client = AlterLab()
```

A `ValueError` is raised only if neither `api_key` nor `ALTERLAB_API_KEY` is set. `AlterLabSync` accepts the same `api_key` parameter and env-var fallback.

The client automatically retries on 429 (rate limit) and 5xx errors with exponential backoff and `Retry-After` header support.

## Async Context Manager

Always use the client as a context manager to properly close connections:

```python
async with AlterLab(api_key="sk_test_...") as client:
    result = await client.scrape("https://example.com")
```

Or close manually:

```python
client = AlterLab(api_key="sk_test_...")
try:
    result = await client.scrape("https://example.com")
finally:
    await client.close()
```

## Billing & Cost Model

AlterLab uses a **dollar-balance** system. All values in the API are in **microcents** (1,000,000 microcents = $1.00).

### Free Trial

New accounts start with **$1.00** (1,000,000 microcents). No credit card required.

### Pricing by Tier

| Tier | Name | Cost per Request | Requests per $1 |
|------|------|-----------------|-----------------|
| 1 | Direct fetch | $0.0002 | 5,000 |
| 2 | Full HTTP client | $0.0003 | 3,333 |
| 3 | Managed sessions | $0.002 | 500 |
| 4 | Full browser rendering | $0.004 | 250 |
| 5 | Extended browser sessions | $0.02 | 50 |

Current prices: [alterlab.io/pricing](https://alterlab.io/pricing). Measured results: [alterlab.io/benchmark](https://alterlab.io/benchmark).

### Checking Your Balance

```python
usage = await client.get_usage()
balance_usd = usage['balance_microcents'] / 1_000_000
print(f"${balance_usd:.4f} remaining")
```

### Adding Balance

Add funds from the [Dashboard Billing page](https://alterlab.io/dashboard/billing).

## Links

- [Dashboard](https://alterlab.io/dashboard) — Get your API key
- [API Documentation](https://alterlab.io/docs) — Full API reference
- [npm package](https://www.npmjs.com/package/alterlab) — Node.js SDK
