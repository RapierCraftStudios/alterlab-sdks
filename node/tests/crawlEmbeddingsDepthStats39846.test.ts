/** Coverage for #39846: crawl forwards `embeddings`; getCrawl forwards `include_depth_stats`. */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

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

describe("crawl/getCrawl param parity (#39846)", () => {
  it("crawl forwards embeddings only when set", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/crawl").reply((config: { data?: string }) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, { crawl_id: "c1", status: "queued" }];
    });
    await client.crawl({
      url: "https://example.com",
      embeddings: { enabled: true, chunk_size: 500 },
    });
    await client.crawl({ url: "https://example.com" });
    expect(bodies[0].embeddings).toEqual({ enabled: true, chunk_size: 500 });
    expect("embeddings" in bodies[1]).toBe(false);
  });

  it("getCrawl sends include_depth_stats only when true", async () => {
    const { client, mock } = makeClient();
    const seen: Record<string, unknown>[] = [];
    mock
      .onGet("/api/v1/crawl/c1")
      .reply((config: { params?: Record<string, unknown> }) => {
        seen.push(config.params ?? {});
        return [200, { crawl_id: "c1", status: "completed" }];
      });
    await client.getCrawl("c1", false, { includeDepthStats: true });
    await client.getCrawl("c1", false, { includeDepthStats: false });
    await client.getCrawl("c1");
    expect(seen[0].include_depth_stats).toBe("true");
    expect("include_depth_stats" in seen[1]).toBe(false);
    expect("include_depth_stats" in seen[2]).toBe(false);
  });
});
