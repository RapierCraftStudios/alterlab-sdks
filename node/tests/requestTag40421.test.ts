/**
 * Coverage for #40421: `tag` is typed on every request and sent on the wire
 * only when set.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const URL = "https://example.com";

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
    return [200, { status: "ok" }];
  };
  for (const path of [
    "/api/v1/scrape",
    "/api/v1/batch",
    "/api/v1/crawl",
    "/api/v1/search",
    "/api/v1/search/batch",
    "/api/v1/map",
    "/api/v1/extract",
  ]) {
    mock.onPost(path).reply(reply);
  }
  return { client, bodies };
}

type Client = AlterLab;
const CALLS: Record<string, (c: Client, tag?: string) => Promise<unknown>> = {
  scrape: (c, tag) => c.scrape({ url: URL, tag }),
  batchScrape: (c, tag) => c.batchScrape({ urls: [{ url: URL }], tag }),
  crawl: (c, tag) => c.crawl({ url: URL, tag }),
  search: (c, tag) => c.search({ query: "alterlab", tag }),
  batchSearch: (c, tag) => c.batchSearch({ queries: ["a", "b"], tag }),
  map: (c, tag) => c.map({ url: URL, tag }),
  extract: (c, tag) => c.extract({ content: "<p>hi</p>", tag }),
};

describe("request tag (#40421)", () => {
  it.each(Object.keys(CALLS))("%s sends tag when set", async (name) => {
    const { client, bodies } = setup();
    await CALLS[name](client, "q3-sweep");
    expect(bodies[0].tag).toBe("q3-sweep");
  });

  it.each(Object.keys(CALLS))("%s omits tag when unset", async (name) => {
    const { client, bodies } = setup();
    await CALLS[name](client);
    expect("tag" in bodies[0] && bodies[0].tag !== undefined).toBe(false);
  });
});
