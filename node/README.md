# alterlab

[![npm](https://img.shields.io/npm/v/alterlab?logo=npm)](https://www.npmjs.com/package/alterlab) [![downloads](https://img.shields.io/npm/dm/alterlab)](https://www.npmjs.com/package/alterlab) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/node)

Official Node.js and TypeScript client for [AlterLab](https://alterlab.io): search, read and extract the live web, with automatic fallback from direct fetch to full browser rendering. Pay only for successful requests.

## Installation

```bash
npm install alterlab
```

## Quick Start

```typescript
import { AlterLab } from "alterlab";

const client = new AlterLab({ apiKey: "sk_test_..." });

const result = await client.scrape({ url: "https://example.com" });
console.log(result.content);
```

Output (the page text for `https://example.com`):

```text
Example Domain

This domain is for use in documentation examples without needing permission. Avoid use in operations.
```

See [pricing](https://alterlab.io/pricing) and the [benchmark](https://alterlab.io/benchmark).

## Methods

### `scrape(request)`

Scrape a single URL.

Sync downgrades are followed automatically: if a synchronous `scrape()` outruns the sync window and the API answers `202` with `sync_downgraded`, the SDK polls the job and returns the real result. Only `sync: false` returns the raw job envelope.

```typescript
// Simple scrape
const result = await client.scrape({ url: "https://example.com" });

// JavaScript rendering with screenshot
const result = await client.scrape({
  url: "https://example.com",
  mode: "js",
  render_js: true,
  screenshot: true,
});
console.log(result.screenshot_url);

// Structured extraction
const result = await client.scrape({
  url: "https://example.com/product",
  extraction_profile: "product",
});
console.log(result.extracted_data);

// With JSON schema extraction
const result = await client.scrape({
  url: "https://example.com/product",
  extraction_schema: {
    type: "object",
    properties: {
      title: { type: "string" },
      price: { type: "number" },
    },
  },
});
```

**`ScrapeRequest` fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `string` | required | URL to scrape |
| `mode` | `string` | `"auto"` | `auto`, `html`, `js`, `pdf`, `ocr` |
| `sync` | `boolean` | `true` | Wait for result (false returns job_id) |
| `response` | `"full" or "minimal"` | server default | `minimal` returns only content, status, url, cost and warnings (default for MCP, agent and keyless keys) |
| `sync_policy` | `"auto" or "wait_until_deadline"` | `"auto"` | `auto` preserves early 202 handoffs; `wait_until_deadline` waits through tier boundaries until terminal completion or the server's 85-second safe deadline (requires `sync: true`) |
| `render_js` | `boolean` | `false` | Enable JavaScript rendering (+3 credits) |
| `screenshot` | `boolean` | `false` | Capture screenshot (+1 credit, needs `render_js`) |
| `markdown` | `boolean` | `false` | Convert to markdown (free) |
| `wait_for` | `string` | — | CSS selector to wait for (JS mode) |
| `timeout` | `number` | — | Request timeout in seconds |
| `force_refresh` | `boolean` | `false` | Bypass cache |
| `extraction_schema` | `object` | — | JSON Schema for structured extraction |
| `extraction_prompt` | `string` | — | Natural language extraction instructions |
| `extraction_profile` | `string` | — | `auto`, `product`, `article`, `job_posting`, `faq`, `recipe`, `event` |
| `max_credits` | `number` | — | Maximum credits for this request |
| `max_tier` | `string` | — | Maximum tier: `0.5`, `1`, `1.5`, `2`, `3`, `4` |

### `crawl(request)`

Start a multi-page website crawl. Returns immediately with a `crawl_id`.

```typescript
const crawl = await client.crawl({
  url: "https://example.com",
  maxPages: 200,
  maxDepth: 2,
  includePatterns: ["/blog/*"],
  formats: ["markdown"],
});
console.log(`Crawl ID: ${crawl.crawl_id}`);
console.log(`Estimated pages: ${crawl.estimated_pages}`);
```

**`CrawlRequest` fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `string` | required | Starting URL |
| `maxPages` | `number` | `50` | Maximum pages (1-100,000) |
| `maxDepth` | `number` | `3` | Link-following depth (0-50) |
| `includePatterns` | `string[]` | — | Glob patterns to include |
| `excludePatterns` | `string[]` | — | Glob patterns to exclude |
| `formats` | `string[]` | — | Output formats per page |
| `extractionSchema` | `object` | — | JSON Schema for each page |
| `extractionProfile` | `string` | — | Extraction profile for each page |
| `webhookUrl` | `string` | — | Webhook for `crawl.completed` |
| `respectRobots` | `boolean` | `true` | Respect robots.txt |
| `includeSubdomains` | `boolean` | `false` | Follow subdomain links |
| `costControls` | `object` | — | `{ maxCredits, maxTier, forceTier }` |

### `crawlAndWait(request, options?)`

Start a crawl and poll until all pages are done.

```typescript
const results = await client.crawlAndWait(
  {
    url: "https://example.com",
    maxPages: 50,
    formats: ["markdown"],
  },
  { pollTimeout: 300000 },
);
console.log(`Pages: ${results.completed}/${results.total}`);
for (const page of results.pages ?? []) {
  console.log(`  ${page.url}: ${page.status}`);
}
```

### `getCrawl(crawlId, includeResults?)`

Get crawl progress. Pass `true` to include per-page results.

```typescript
const status = await client.getCrawl(crawlId);
console.log(`${status.completed}/${status.total} pages done`);
```

### `cancelCrawl(crawlId)`

Cancel a running crawl. Credits for unprocessed pages are refunded.

```typescript
const result = await client.cancelCrawl(crawlId);
console.log(`Refunded ${result.credits_refunded} credits`);
```

### `batchScrape(request, webhookUrl?)`

Submit up to 100 URLs as a batch. `request` is either a `BatchRequest`
(`urls`, `session_id`, `export`, batch-level `extraction_*` defaults) or a plain
array of items. Item shorthands (`render_js`, `screenshot`, `markdown`,
`use_proxy`, `scroll_to_load`, `scroll_count`, `section_filter`, `max_credits`,
`max_tier`) are sent under `advanced` / `cost_controls`.

Proxy intent is three-state: leave `use_proxy` (or `advanced.useProxy`) unset to
let the platform route through a proxy only when the target needs it, set
`false` to keep direct routing, or `true` to always use the premium proxy. An
unset value is never sent as `false`.

```typescript
const batch = await client.batchScrape({
  urls: [
    { url: "https://example.com/page1" },
    { url: "https://example.com/page2" },
  ],
  session_id: "3f0c…",
  export: { integration_id: "9a1d…", format: "jsonl" },
  extraction_profile: "product",
  extraction_provider: "openai",
  webhook_url: "https://myapp.com/webhook",
});
```

The array form is also accepted:

```typescript
const batch = await client.batchScrape(
  [
    { url: "https://example.com/page1", mode: "html" },
    { url: "https://example.com/page2", mode: "js" },
  ],
  "https://myapp.com/webhook",
);

for (const jobId of batch.job_ids) {
  const result = await client.waitForJob(jobId);
  console.log(result.result?.content.length);
}
```

### `search(request)`

Unified, vendor-neutral search with page content by default. `search({ query })` runs
`engine: "auto"` on `/v1/search` and returns each result page as concise markdown with a
per-result `content_status` (`scrape_results: true`, `concise: true`, `mode: "standard"`). The
unified query is a flat $0.001; each fetched page bills at its fetch tier. Pass
`scrape_results: false` for the result list only. The SDK default engine is `auto`; the REST API's own default stays `duckduckgo`. An explicit `engine` keeps that engine's
behaviour (no content unless asked for, plain requests use `/v1/serp`).

```typescript
const unified = await client.search({ query: "headless browsers" }); // unified, with content

// Served by /v1/serp: read `organic_results` from the response JSON.
const results = await client.search({
  query: "headless browsers",
  engine: "google",
  num: 10,
  start: 0,
  device: "desktop",
});
```

| Engine | Price per query |
| --- | --- |
| `duckduckgo` | $0.001 |
| `google` | $0.004 |
| `bing` | $0.004 |

With `scrape_results`, pass `sync: true` to wait up to ~30s and get content in one call; on timeout the
response is a 202 with `next_action` (poll the search id).

`scrape_results`, `domain`, `time_range` and the unified engine are served by `/v1/search`, so
requests that use them are sent there. The response is the JSON of the endpoint used: `organic_results` from
`/v1/serp`, `results` from the alias. See the
[migration guide](https://alterlab.io/docs/migrations/search-to-serp).

### `research(request)` and the research job methods

Budgeted deep research on your own model key (BYOK; a missing key returns `byok_key_required`
and charges nothing). Every claim in the result carries citations.

```ts
const job = await client.research({
  query: "Which EU countries ban fur farming?",
  effort: "standard",
  max_cost_microcents: 50_000,
  output: "both",
});
const done = await client.waitForResearch(job.id); // completed | completed_partial | failed | cancelled
console.log(done.status, done.cost, done.result);
```

Also: `getResearch(id)`, `cancelResearch(id)`, `researchEvents(id, lastEventId?)` (progress
events, resumable), and for `plan_first` jobs `getResearchPlan(id)`, `updateResearchPlan(id, plan)`
and `approveResearch(id, plan?)`. See the [API reference](https://alterlab.io/docs/api/research).

### `batchSearch(request)` and `getBatchSearch(batchId)`

Submit and poll a batch of search queries. Each query is billed at the engine rate above.

### `feedback(request)`

Tell AlterLab what was hard. Returns `cluster_key` and `statusUrl`. Never include customer data.

```ts
const r = await client.feedback({
  category: "blocked",
  tried: "mode=auto",
  happened: "empty body with 200",
  jobId: "job_123",
});
console.log(r.cluster_key, r.statusUrl);
```

Optional `what_failed`, `what_tried` and `what_expected` send the API's wire fields directly and override the values derived from `category`/`happened`/`tried`/`expected`/`jobId`.

### `estimateCost(request)`

Get a cost estimate before scraping.

```typescript
const estimate = await client.estimateCost({
  url: "https://example.com",
  mode: "js",
});
console.log(`Estimated: ${estimate.estimated_credits} credits`);
console.log(`Max possible: ${estimate.max_possible_credits} credits`);
```

### `getUsage()`

Check your credit balance and usage stats.

```typescript
const usage = await client.getUsage();
console.log(`Balance: ${usage.balance_microcents} microcents`);
console.log(`Account tier: ${usage.account_tier}`);
console.log(`Entitlement source: ${usage.entitlement_source}`);
```

### `waitForJob(jobId, options?)`

Poll an async job until completion with exponential backoff.

```typescript
const result = await client.waitForJob(jobId, {
  pollInterval: 2000,
  pollTimeout: 300000,
  backoffMultiplier: 1.5,
  maxInterval: 30000,
});
```

### `getJobStatus(jobId)`

Check job status without waiting.

```typescript
const job = await client.getJobStatus(jobId);
console.log(`Status: ${job.status}`);
```

## Client Options

```typescript
const client = new AlterLab({
  apiKey: "sk_test_...",                    // Required
  baseUrl: "https://api.alterlab.io",       // Default API URL
  maxRetries: 3,                            // Retry count for transient failures
  retryDelay: 1000,                         // Initial retry delay in ms (jittered exponential backoff)
  maxRetryWait: 60000,                      // Max total ms spent waiting between retries (null = no cap)
  logger: silentLogger,                     // Custom logger (or silentLogger to disable)
});
```

The client automatically retries on 429 (rate limit) and 5xx errors with jittered exponential backoff. A `Retry-After` header is honoured as a minimum wait; if waiting it out would exceed `maxRetryWait`, the error is thrown immediately. A 429 is thrown as `RateLimitError` (an `AxiosError` subclass) exposing `retryAfter`, `errorCode`, `scope`, `limit`, `accountTier`, `docsUrl`, `rateLimit*` and `hint` fields (`null` for edge 429s without the canonical body). For `errorCode === "repeat_failure_backoff"` (the same request failed the same way several times in a row; no credits charged) it also exposes `consecutiveFailures`, `outcomeClass` and `failureCode`, and `getErrorHint(e)` returns its hint: retry after `retryAfter`, with different request options, or with `forceRefresh: true`.

### Custom Logger

```typescript
import { silentLogger } from "alterlab";

// Silent mode (no console output)
const client = new AlterLab({ apiKey: "...", logger: silentLogger });

// Custom logger
const client = new AlterLab({
  apiKey: "...",
  logger: {
    debug: (msg) => myLogger.debug(msg),
    warn: (msg) => myLogger.warn(msg),
    error: (msg) => myLogger.error(msg),
  },
});
```

## Browser actions

Run a sequence of browser actions after page load (max 20, requires `render_js: true`).
`actions` is typed as `ScrapeAction[]`, a discriminated union on `type`; build entries
with the `Actions` helpers or as object literals.

```typescript
import { AlterLab, Actions, ScrapeAction } from "alterlab";

// Screenshot after actions: click, wait, then capture the resulting page
const actions: ScrapeAction[] = [
  Actions.dismissConsent(),
  Actions.click("button.load-more"),
  Actions.wait({ milliseconds: 1000 }),
  { type: "evaluate", script: "document.title" },
  Actions.screenshot(true),
];

const result = await client.scrape({
  url: "https://example.com/products",
  render_js: true,
  actions,
});

for (const ar of result.action_results ?? []) {
  console.log(ar.index, ar.type, ar.success, ar.error);
}
const title = result.action_results?.[3]?.result;
const screenshotUrl = result.action_results?.[4]?.screenshot_url;
```

Available builders: `wait`, `waitFor`, `click`, `fill`, `press`, `scroll`,
`infiniteScroll`, `screenshot`, `evaluate`, `dismissConsent`. Failed actions are
skipped; check `success` and `error` on each result.

### Downloading files

`Actions.download({ selector | url })` captures a file download started by the
page (exactly one of `selector` or `url`; `timeout_ms` 1000-30000, optional
`max_bytes` up to 100 MiB, `frame` only with `selector`; at most 5 per request,
checked client-side). The file is stored privately and the matching action
result carries `artifact` (`ArtifactMetadata`: `artifact_id`, `filename`,
`media_type`, `size_bytes`, `sha256`, `scan_status`, `expires_at`).

Multi-file: `max_files` (1-10) collects several files into `artifacts`;
`max_total_bytes` caps their total size, `quiet_ms` (100-10000) ends collection
after an idle period and `bundle: "zip"` also stores a ZIP, returned as `bundle`
(the last three need `max_files > 1`).

```typescript
const result = await client.scrape({
  url: "https://example.com/reports",
  render_js: true,
  actions: [Actions.click("#export"), Actions.download({ selector: "a.csv" })],
});
const artifact = result.action_results?.[1]?.artifact;
if (artifact) {
  await client.getArtifact(artifact.artifact_id); // metadata
  (await client.getArtifactUrl(artifact.artifact_id)).url; // short-lived signed URL
  await client.downloadArtifact(artifact.artifact_id, "report.csv"); // saves the file
}
```

The download is fetched without your API key and written atomically (a failed
download leaves no file). The helpers are also exported as `getArtifact`,
`getArtifactUrl` and `downloadArtifact` taking an `ArtifactTransport`.

## Drop-in `fetch()` wrapper

If your agent already writes standard `fetch(url, options)` code, you can route it through
AlterLab (automatic fallback from direct fetch to full browser rendering) without rewriting call sites — just swap the import and, since a
real `fetch()` carries no auth, supply your API key once via `createFetch()`:

```typescript
import { createFetch } from "alterlab";

const fetch = createFetch({ apiKey: "sk_test_..." });

const response = await fetch("https://example.com", {
  method: "GET",
  headers: { "X-Custom-Header": "value" },
});

console.log(response.status, response.ok);
console.log(await response.text());
// console.log(await response.json());
```

The returned object implements the `Response` surface most fetch-based code relies on:
`.status`, `.ok`, `.statusText`, `.headers` (with a case-insensitive `.get(name)`), `.text()`,
and `.json()`. Custom headers are forwarded to the target site. Internally it calls the same
`/api/v1/scrape` endpoint as `client.scrape()` — no separate backend endpoint is used.

**Supported methods: `GET`, `POST` only.** This matches the underlying `/api/v1/scrape`
API, which does not accept `HEAD`, `OPTIONS`, `PUT`, `PATCH`, or `DELETE`. Calling `fetch()`
with any other method throws a clear client-side error immediately rather than sending a
request the API would reject with HTTP 422.

**Error handling differs from `client.scrape()`.** This wrapper matches native `fetch()`
semantics: an AlterLab API HTTP error (rate limit, validation error, auth error, etc.)
**resolves** the returned promise with `ok: false` and a non-2xx `status` — it does not
throw or reject. Only genuine network-level failures (no response at all) reject. Check
`response.ok` rather than wrapping the call in `try`/`catch`:

```typescript
const response = await fetch("https://example.com");
if (!response.ok) {
  console.error(`AlterLab API error: ${response.status}`);
  return;
}
console.log(await response.text());
```

This is the opposite of `client.scrape()` (see [Error Handling](#error-handling) below),
which throws on the same class of AlterLab API errors — don't reuse `try`/`catch` logic
written for `client.scrape()` around the `fetch()` wrapper.

**Custom logger.** `createFetch()` accepts the same `logger` option as the `AlterLab` client
(see [Custom Logger](#custom-logger) above) — it controls debug/warn/error output, including
the debug log emitted when a request's `Content-Type` header is unrecognized and dropped.
Defaults to a console-based logger; pass `silentLogger` to disable output entirely:

```typescript
import { createFetch, silentLogger } from "alterlab";

const fetch = createFetch({ apiKey: "sk_test_...", logger: silentLogger });
```

If your process already exports `ALTERLAB_API_KEY` into its environment (common for agent
runtimes), you can use the literal drop-in import instead:

```typescript
import { fetch } from "alterlab";

const response = await fetch("https://example.com");
```

`fetch` throws a clear error if `ALTERLAB_API_KEY` is unset, rather than making an
unauthenticated request.

## TypeScript

The SDK exports full TypeScript types for all requests and responses:

```typescript
import type {
  ScrapeRequest,
  ScrapeResponse,
  CrawlRequest,
  CrawlResponse,
  CrawlStatusResponse,
  BatchScrapeRequest,
  BatchResponse,
  CostEstimateRequest,
  CostEstimateResponse,
  JobStatusResponse,
  UsageStats,
  AlterLabOptions,
  WaitForJobOptions,
  CrawlAndWaitOptions,
} from "alterlab";
```

## Error Handling

```typescript
try {
  const result = await client.scrape({ url: "https://example.com" });
} catch (error) {
  if (axios.isAxiosError(error)) {
    console.log(`HTTP ${error.response?.status}: ${error.response?.data}`);
  } else {
    console.log(`Error: ${error.message}`);
  }
}
```

Errors from the API include the HTTP status code and detail message in the Axios error response. The SDK retries transient errors (429, 5xx) automatically.

### Retry hints

When a request forces browser rendering (`render_js: true` or `cost_controls.force_tier: "4"`) and the page returns a verification screen or does not finish loading in time, the error carries a `hint`. `getErrorHint` reads it from a failed sync scrape, a `JobFailedError` (also exposed as `error.hint`) or a crawl page's `error` object:

```typescript
import { getErrorHint } from "alterlab";

try {
  await client.scrape({ url: "https://example.com", render_js: true });
} catch (error) {
  const hint = getErrorHint(error);
  if (hint?.code === "render_js_auto") {
    console.log(hint.message);
    // Retry with render_js: "auto" so the platform starts at the lowest tier that returns the page
  }
}
```

For pages that only sometimes need a browser, prefer `render_js: "auto"` from the start. Keep `render_js: true` for `screenshot`, PDF and browser `actions`.

## Links

- [Dashboard](https://alterlab.io/dashboard) — Get your API key
- [API Documentation](https://alterlab.io/docs) — Full API reference
- [PyPI package](https://pypi.org/project/alterlab/) — Python SDK
