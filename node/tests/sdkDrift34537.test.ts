/**
 * Coverage for #34537: Node SDK request contracts for batch, cost estimate and
 * session update/refresh match the API's OpenAPI request schemas.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const BATCH_RESPONSE = {
  batch_id: "b1",
  total_urls: 1,
  estimated_credits: 1,
  job_ids: ["j1"],
  status: "queued",
  accepted_urls: 1,
  rejected_urls: 0,
  rejected_items: [],
  byos_applied: false,
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
  const bodies: Record<string, unknown>[] = [];
  const capture =
    (response: unknown) =>
    (config: { data?: string }): [number, unknown] => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, response];
    };
  return { client, mock, bodies, capture };
}

describe("batchScrape (#34537)", () => {
  it("posts items under `urls` (the API rejects `requests`)", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/batch").reply(capture(BATCH_RESPONSE));

    await client.batchScrape(
      [{ url: "https://example.com/a", mode: "html" }],
      "https://hooks.example.com/batch",
    );

    expect(bodies[0]).toEqual({
      urls: [{ url: "https://example.com/a", mode: "html" }],
      webhook_url: "https://hooks.example.com/batch",
    });
    expect(bodies[0]).not.toHaveProperty("requests");
  });

  it("passes batch-level fields from a BatchRequest", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/batch").reply(capture(BATCH_RESPONSE));

    await client.batchScrape({
      urls: [{ url: "https://example.com/a" }],
      session_id: "6f1c2a8e-1d0b-4c55-9a43-2b8f8c1d7e10",
      export: { integration_id: "int-1", format: "csv" },
      extraction_provider: "anthropic",
      extraction_profile: "product",
      webhook_url: "https://hooks.example.com/batch",
    });

    expect(bodies[0]).toEqual({
      urls: [{ url: "https://example.com/a" }],
      session_id: "6f1c2a8e-1d0b-4c55-9a43-2b8f8c1d7e10",
      export: { integration_id: "int-1", format: "csv" },
      extraction_provider: "anthropic",
      extraction_profile: "product",
      webhook_url: "https://hooks.example.com/batch",
    });
  });

  it("moves item shorthands into advanced/cost_controls; explicit values win", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/batch").reply(capture(BATCH_RESPONSE));

    await client.batchScrape([
      {
        url: "https://example.com/a",
        render_js: true,
        screenshot: true,
        scroll_to_load: true,
        scroll_count: 4,
        max_credits: 10,
        max_tier: "3",
        advanced: { screenshot: false, use_proxy: true },
        cost_controls: { fail_fast: true },
      },
    ]);

    expect(bodies[0].urls).toEqual([
      {
        url: "https://example.com/a",
        advanced: {
          render_js: true,
          screenshot: false,
          scroll_to_load: true,
          scroll_count: 4,
          use_proxy: true,
        },
        cost_controls: { max_credits: 10, max_tier: "3", fail_fast: true },
      },
    ]);
  });
});

describe("estimateCost (#34537)", () => {
  it("sends the full UnifiedScrapeRequest body", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock
      .onPost("/api/v1/scrape/estimate")
      .reply(capture({ url: "https://example.com" }));

    const request = {
      url: "https://example.com",
      method: "POST" as const,
      body: '{"q":1}',
      content_type: "application/json" as const,
      headers: { "X-Test": "1" },
      cache: true,
      cache_ttl: 600,
      location: { country: "DE" },
      extraction_provider: "openai" as const,
      extraction_model: "gpt-4o",
      max_response_bytes: 1024,
      wait_until: "load",
      webhook_url: "https://hooks.example.com/scrape",
    };
    await client.estimateCost(request);

    expect(bodies[0]).toEqual(request);
  });
});

describe("sessions.update / sessions.refresh (#34537)", () => {
  it("update sends notification and auto-refresh flags", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPatch("/api/v1/sessions/s1").reply(capture({ id: "s1" }));

    await client.sessions.update("s1", {
      auto_refresh_enabled: true,
      notify_before_expiry: false,
      notify_on_failure: true,
    });

    expect(bodies[0]).toEqual({
      auto_refresh_enabled: true,
      notify_before_expiry: false,
      notify_on_failure: true,
    });
  });

  it("refresh supports client-side encryption without plaintext cookies", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/sessions/s1/refresh").reply(capture({ id: "s1" }));

    await client.sessions.refresh("s1", {
      encryption_mode: "client",
      encrypted_cookies: "aXY=.Y3Q=",
      wrapped_key: "d2s=",
      cookie_names: ["sid"],
      key_version: 2,
    });

    expect(bodies[0]).toEqual({
      encryption_mode: "client",
      encrypted_cookies: "aXY=.Y3Q=",
      wrapped_key: "d2s=",
      cookie_names: ["sid"],
      key_version: 2,
    });
  });
});
