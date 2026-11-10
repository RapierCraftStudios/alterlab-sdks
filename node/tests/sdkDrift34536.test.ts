/**
 * Coverage for #34536: Node SDK response types for scrape, search, batch
 * search, crawl and crawl status expose every field the API's OpenAPI
 * response schemas define.
 *
 * ts-jest type-checks this file, so reading a field the SDK interfaces do not
 * declare fails compilation — the typed accesses below are the regression
 * guard; the runtime assertions confirm the payload passes through intact.
 */
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  BatchSearchResponse,
  CrawlResponse,
  CrawlStatusResponse,
  ScrapeResponse,
  SearchResponse,
} from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

describe("scrape response fields (#34536)", () => {
  it("types the UnifiedScrapeResponse fields", async () => {
    const { client, mock } = makeClient();
    const payload = {
      url: "https://example.com",
      status_code: 200,
      content: "hello",
      headers: {},
      cached: true,
      response_time_ms: 10,
      size_bytes: 5,
      version: "v1",
      job_id: "job-1",
      title: "Example",
      author: null,
      published_at: "2026-01-01",
      metadata: { og_title: "Example" },
      raw_html: "<html></html>",
      raw: "<html></html>",
      structured_content: [{ type: "p" }],
      structured_sections: [{ heading: "h" }],
      ocr_results: null,
      extraction_method: "algorithmic",
      method_details: null,
      extraction_completeness: 0.9,
      extraction_note: null,
      is_gated: false,
      content_hash: "0123456789abcdef",
      content_truncated: {
        truncated: true,
        truncated_at_bytes: 100,
        original_size_bytes: 200,
        truncation_reason: "response_body_cap",
      },
      cached_at: "2026-01-01T00:00:00Z",
      expires_at: "2026-01-02T00:00:00Z",
      stale_cache: false,
      proxy_used: { id: "p1", provider: "x", name: "mine" },
      action_results: [{ index: 0, type: "click", success: true }],
      embeddings: {
        model: "m",
        dimensions: 2,
        chunks: [
          {
            text: "hello",
            embedding: [0.1, 0.2],
            start_index: 0,
            end_index: 5,
          },
        ],
        total_tokens: 1,
        total_chunks: 1,
      },
    };
    mock.onPost("/api/v1/scrape").reply(200, payload);

    const res: ScrapeResponse = await client.scrape({ url: payload.url });

    expect(res.version).toBe("v1");
    expect(res.job_id).toBe("job-1");
    expect(res.title).toBe("Example");
    expect(res.author).toBeNull();
    expect(res.metadata?.og_title).toBe("Example");
    expect(res.content_hash).toHaveLength(16);
    expect(res.content_truncated?.truncation_reason).toBe("response_body_cap");
    expect(res.action_results?.[0].success).toBe(true);
    expect(res.embeddings?.chunks[0].embedding).toEqual([0.1, 0.2]);
    expect(res.is_gated).toBe(false);
    expect(res.stale_cache).toBe(false);
    expect(res.extraction_completeness).toBe(0.9);
    expect(res.cached_at).toBe(payload.cached_at);
    expect(res.expires_at).toBe(payload.expires_at);
    expect(res.proxy_used?.provider).toBe("x");
    expect(res.structured_content).toHaveLength(1);
    expect(res.structured_sections).toHaveLength(1);
    expect(res.raw_html).toBe(res.raw);
    expect([
      res.published_at,
      res.ocr_results,
      res.extraction_method,
      res.method_details,
      res.extraction_note,
    ]).toEqual(["2026-01-01", null, "algorithmic", null, null]);
  });
});

describe("search response fields (#34536)", () => {
  it("types the SearchResponse SERP features and counters", async () => {
    const { client, mock } = makeClient();
    const payload = {
      search_id: "s1",
      query: "q",
      results_requested: 10,
      results_count: 1,
      estimated_total_results: 1230000,
      did_you_mean: "query",
      credits_used: 1,
      results: [],
      ad_results: [
        {
          position: 1,
          slot: "top",
          sitelinks: [{ title: "t", url: "https://a.example" }],
        },
      ],
      local_results: [{ name: "Cafe", rating: 4.5 }],
      news_results: [{ title: "News", url: "https://n.example" }],
      image_results: [{ image_url: "https://i.example/x.png" }],
      video_results: [{ title: "Vid", url: "https://v.example" }],
      shopping_results: [{ title: "Thing", price: "$1" }],
      warnings: [
        { code: "scraping_skipped_insufficient_credits", message: "m" },
      ],
    };
    mock.onPost("/api/v1/serp").reply(200, payload);

    const raw = await client.search({ query: "q", engine: "google" });
    if ("queries_count" in raw) throw new Error("expected a single-query response");
    const res: SearchResponse = raw;

    expect(res.results_requested).toBe(10);
    expect(res.results_count).toBe(1);
    expect(res.estimated_total_results).toBe(1230000);
    expect(res.did_you_mean).toBe("query");
    expect(res.ad_results?.[0].sitelinks?.[0].url).toBe("https://a.example");
    expect(res.local_results?.[0].rating).toBe(4.5);
    expect(res.news_results?.[0].url).toBe("https://n.example");
    expect(res.image_results?.[0].image_url).toContain("x.png");
    expect(res.video_results?.[0].title).toBe("Vid");
    expect(res.shopping_results?.[0].price).toBe("$1");
    expect(res.warnings?.[0].code).toBe(
      "scraping_skipped_insufficient_credits",
    );
  });

  it("types the BatchSearchResponse message", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/search/batch").reply(202, {
      batch_id: "b1",
      total_queries: 1,
      status: "queued",
      estimated_credits: 1,
      job_ids: ["j1"],
      message: "Batch search submitted.",
    });

    const res: BatchSearchResponse = await client.batchSearch({
      queries: ["q"],
    });

    expect(res.message).toBe("Batch search submitted.");
  });
});

describe("crawl response fields (#34536)", () => {
  it("types the CrawlResponse slot and storage fields", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/crawl").reply(202, {
      crawl_id: "c1",
      status: "discovering",
      estimated_pages: 10,
      total_enqueued: 1,
      estimated_credits: 10,
      message: "ok",
      storage: "r2",
      crawl_slot_limit: 3,
      crawl_slot_tier: "free",
      effective_max_concurrency: 2,
    });

    const res: CrawlResponse = await client.crawl({
      url: "https://example.com",
    });

    expect(res.storage).toBe("r2");
    expect(res.crawl_slot_limit).toBe(3);
    expect(res.crawl_slot_tier).toBe("free");
    expect(res.effective_max_concurrency).toBe(2);
  });

  it("types the CrawlStatusResponse analytics and storage fields", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/crawl/c1").reply(200, {
      crawl_id: "c1",
      status: "completed",
      total: 1,
      completed: 1,
      failed: 0,
      in_progress: 0,
      credits_debited: 1,
      created_at: "2026-01-01T00:00:00Z",
      current_depth: 0,
      max_depth: 1,
      total_discovered: 1,
      active_depths: [],
      depth_stats: [{ depth: 0, total: 1, succeeded: 1 }],
      budget_status: { budget: { "*": 5 }, counts: { "*": 1 }, exhausted: [] },
      effective_crawl_delay: 0.5,
      pagination: { offset: 0, limit: 50, total_matching: 1, has_more: false },
      change_summary: { new_pages: 1, removed_urls: [] },
      output_status: { type: "s3", pages_exported: 1 },
      storage_backend: "r2",
      results_url: "https://r2.example/results.jsonl",
      results_expiry: "2026-02-01T00:00:00Z",
    });

    const res: CrawlStatusResponse = await client.getCrawl("c1");

    expect(res.active_depths).toEqual([]);
    expect(res.depth_stats?.[0].succeeded).toBe(1);
    expect(res.budget_status?.counts["*"]).toBe(1);
    expect(res.effective_crawl_delay).toBe(0.5);
    expect(res.pagination?.has_more).toBe(false);
    expect(res.change_summary?.new_pages).toBe(1);
    expect(res.output_status?.pages_exported).toBe(1);
    expect(res.storage_backend).toBe("r2");
    expect(res.results_url).toContain("results.jsonl");
    expect(res.results_expiry).toBe("2026-02-01T00:00:00Z");
  });
});
