/**
 * Coverage for #40403: `dry_run` on batchScrape and `dryRun` on crawl are typed
 * and sent on the wire only when set.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function setup() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: Record<string, unknown>[] = [];
  const reply = (config: { data?: string }) => {
    bodies.push(JSON.parse(config.data as string));
    return [200, { dry_run: true, status: "dry_run" }];
  };
  mock.onPost("/api/v1/batch").reply(reply);
  mock.onPost("/api/v1/crawl").reply(reply);
  return { client, bodies };
}

describe("dry_run (#40403)", () => {
  it("batchScrape forwards dry_run", async () => {
    const { client, bodies } = setup();
    await client.batchScrape({
      urls: [{ url: "https://example.com/a" }],
      dry_run: true,
    });
    expect(bodies[0].dry_run).toBe(true);
  });

  it("crawl maps dryRun to dry_run", async () => {
    const { client, bodies } = setup();
    await client.crawl({ url: "https://example.com", dryRun: true });
    expect(bodies[0].dry_run).toBe(true);
  });

  it("omits dry_run by default", async () => {
    const { client, bodies } = setup();
    await client.batchScrape([{ url: "https://example.com/a" }]);
    await client.crawl({ url: "https://example.com" });
    expect(bodies.every((b) => !("dry_run" in b))).toBe(true);
  });
});
