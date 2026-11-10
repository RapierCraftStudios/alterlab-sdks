/**
 * Coverage for #36801: Node SDK search request/response contracts and status polling.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, SearchResponse } from "../src/index";

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

describe("search (#36801)", () => {
  it("sends engine, safe_search and rag", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/search").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { search_id: "s", query: "q", results: [] }];
    });
    await client.search({
      query: "q",
      engine: "bing",
      safe_search: true,
      scrape_results: true,
      formats: ["rag"],
    });
    expect(body).toMatchObject({
      engine: "bing",
      safe_search: true,
      formats: ["rag"],
    });
  });

  it("routes the unified engine=auto to /v1/search (#38613)", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/search").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { search_id: "s", query: "q", results: [] }];
    });
    await client.search({ query: "q", engine: "auto" });
    expect(body).toMatchObject({ engine: "auto" });
  });

  it("defaults to unified search with concise content, and the defaults turn off (#38613)", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/search").reply((config) => {
      bodies.push(JSON.parse(config.data));
      return [200, { search_id: "s", query: "q", results: [] }];
    });
    await client.search({ query: "q" });
    await client.search({ query: "q", scrape_results: false });
    await client.search({ query: "q", concise: false, wait: 7 });
    await client.search({ queries: ["a", "b"] });
    expect(bodies[0]).toMatchObject({
      engine: "auto",
      scrape_results: true,
      preset: "agent",
      mode: "standard",
    });
    expect(bodies[0]).not.toHaveProperty("concise");
    expect(bodies[1]).toMatchObject({ engine: "auto", scrape_results: false });
    expect(bodies[1]).not.toHaveProperty("preset");
    expect(bodies[2]).not.toHaveProperty("preset");
    expect(bodies[2]).not.toHaveProperty("mode");
    expect(bodies[3]).toMatchObject({ engine: "auto", scrape_results: false });
  });

  it("posts to /v1/serp with device, num, start and a duckduckgo default engine", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/serp").reply((config) => {
      bodies.push(JSON.parse(config.data));
      return [
        200,
        { search_id: "s", query: "q", results: [], engine_used: "google" },
      ];
    });
    const res = await client.search({
      query: "q",
      engine: "google",
      device: "mobile",
      num: 20,
      start: 20,
    });
    await client.search({ query: "q", engine: "duckduckgo" });
    expect((res as SearchResponse).engine_used).toBe("google");
    expect(bodies[0]).toMatchObject({
      engine: "google",
      device: "mobile",
      num_results: 20,
      start: 20,
    });
    expect(bodies[0]).not.toHaveProperty("num");
    expect(bodies[1]).toMatchObject({ engine: "duckduckgo" });
  });

  it("keeps scrape_results, domain and time_range on the /v1/search alias", async () => {
    const { client, mock } = makeClient();
    const urls: string[] = [];
    mock.onPost().reply((config) => {
      urls.push(config.url ?? "");
      return [200, { search_id: "s", query: "q", results: [] }];
    });
    await client.search({ query: "q", engine: "google", scrape_results: true });
    await client.search({
      query: "q",
      engine: "google",
      domain: "example.com",
    });
    await client.search({ query: "q", engine: "google", time_range: "day" });
    expect(urls).toEqual([
      "/api/v1/search",
      "/api/v1/search",
      "/api/v1/search",
    ]);
  });

  it("SearchResponse uses estimated_total_results and no required total_results", () => {
    const r: SearchResponse = {
      search_id: "s",
      query: "q",
      results: [],
      credits_used: 1,
      results_requested: 10,
      results_count: 0,
      estimated_total_results: 5,
    };
    expect(r.estimated_total_results).toBe(5);
  });

  it("polls single and batch status", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/search/s1").reply(200, {
      search_id: "s1",
      query: "q",
      status: "completed",
      results_requested: 1,
      results_count: 1,
      completed: 1,
    });
    mock.onGet("/api/v1/search/batch/b1").reply(200, {
      batch_id: "b1",
      status: "processing",
      total: 2,
      completed: 1,
      failed: 0,
      pending: 1,
      items: [],
      total_credits_used: 0,
      created_at: "now",
    });
    expect((await client.getSearch("s1")).status).toBe("completed");
    expect((await client.getBatchSearch("b1")).pending).toBe(1);
  });
});
