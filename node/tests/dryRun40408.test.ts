/**
 * Coverage for #40408: batchScrape and crawl accept and forward dry_run.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchRequest, CrawlRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function setup(path: string) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: Record<string, unknown>[] = [];
  mock.onPost(path).reply((config: { data?: string }) => {
    bodies.push(JSON.parse(config.data ?? "{}"));
    return [200, { status: "ok" }];
  });
  return { client, bodies };
}

describe("dry_run (#40408)", () => {
  it("batchScrape forwards dry_run", async () => {
    const { client, bodies } = setup("/api/v1/batch");
    const request: BatchRequest = {
      urls: [{ url: "https://example.com" }],
      dry_run: true,
    };
    await client.batchScrape(request);
    expect(bodies[0].dry_run).toBe(true);
  });

  it("crawl forwards dryRun as dry_run", async () => {
    const { client, bodies } = setup("/api/v1/crawl");
    const request: CrawlRequest = {
      url: "https://example.com",
      dryRun: true,
    };
    await client.crawl(request);
    expect(bodies[0].dry_run).toBe(true);
  });

  it("crawl omits dry_run when unset", async () => {
    const { client, bodies } = setup("/api/v1/crawl");
    await client.crawl({ url: "https://example.com" });
    expect(bodies[0]).not.toHaveProperty("dry_run");
  });
});
