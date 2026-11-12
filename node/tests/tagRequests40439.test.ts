/**
 * Coverage for #40439: `tag` is typed on scrape, batchScrape, batchSearch,
 * extract, map and search requests and sent on the wire only when set.
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
  mock.onPost().reply((config) => {
    bodies.push(JSON.parse(config.data as string));
    return [200, { status: "ok" }];
  });
  return { client, bodies };
}

type Call = (c: AlterLab, tag?: string) => Promise<unknown>;
const U = "https://example.com";
const CALLS: [string, Call][] = [
  ["scrape", (c, tag) => c.scrape({ url: U, tag })],
  ["batchScrape", (c, tag) => c.batchScrape({ urls: [{ url: U }], tag })],
  ["batchSearch", (c, tag) => c.batchSearch({ queries: ["a"], tag })],
  ["extract", (c, tag) => c.extract({ content: "x", tag })],
  ["map", (c, tag) => c.map({ url: U, tag })],
  ["search", (c, tag) => c.search({ query: "a", tag })],
];

describe("request tag (#40439)", () => {
  it.each(CALLS)("%s sends tag when set", async (_n, call) => {
    const { client, bodies } = setup();
    await call(client, "team-a");
    expect(bodies[0].tag).toBe("team-a");
  });

  it.each(CALLS)("%s omits tag by default", async (_n, call) => {
    const { client, bodies } = setup();
    await call(client);
    expect(bodies[0]).not.toHaveProperty("tag");
  });
});
