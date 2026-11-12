/**
 * Coverage for #40423: the spend-attribution `tag` is typed and forwarded by
 * scrape, estimateCost, batchSearch, extract, batchScrape, crawl, map and search.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

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

type Call = (c: AlterLab, tag?: string) => Promise<unknown>;

const CASES: [string, string, Call][] = [
  [
    "scrape",
    "/api/v1/scrape",
    (c, tag) => c.scrape({ url: "https://example.com", tag }),
  ],
  [
    "estimateCost",
    "/api/v1/scrape/estimate",
    (c, tag) => c.estimateCost({ url: "https://example.com", tag }),
  ],
  [
    "batchSearch",
    "/api/v1/search/batch",
    (c, tag) => c.batchSearch({ queries: ["a"], tag }),
  ],
  ["extract", "/api/v1/extract", (c, tag) => c.extract({ content: "x", tag })],
  [
    "batchScrape",
    "/api/v1/batch",
    (c, tag) => c.batchScrape({ urls: [{ url: "https://example.com" }], tag }),
  ],
  [
    "crawl",
    "/api/v1/crawl",
    (c, tag) => c.crawl({ url: "https://example.com", tag }),
  ],
  [
    "map",
    "/api/v1/map",
    (c, tag) => c.map({ url: "https://example.com", tag }),
  ],
];

describe("tag (#40423)", () => {
  it.each(CASES)("%s forwards tag", async (_name, path, call) => {
    const { client, bodies } = setup(path);
    await call(client, "team-a");
    expect(bodies[0].tag).toBe("team-a");
  });

  it.each(CASES)("%s omits tag when unset", async (_name, path, call) => {
    const { client, bodies } = setup(path);
    await call(client);
    expect(bodies[0]).not.toHaveProperty("tag");
  });
});
