/**
 * Coverage for #38991: `response` on scrape and `sync` on search are forwarded
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

describe("agent-grade params (#38991)", () => {
  it("scrape forwards response=minimal and returns the body untouched", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    const minimal = { content: "hi", status_code: 200, url: "https://e.com" };
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [200, minimal];
    });
    const res = await client.scrape({
      url: "https://e.com",
      response: "minimal",
    });
    expect(body.response).toBe("minimal");
    expect(res).toEqual(minimal);
  });

  it("scrape omits response by default", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { content: "hi", status_code: 200 }];
    });
    await client.scrape({ url: "https://e.com" });
    expect("response" in body).toBe(false);
  });

  it("search forwards sync to /api/v1/search and omits it by default", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    const urls: string[] = [];
    mock.onPost().reply((config) => {
      urls.push(config.url ?? "");
      bodies.push(JSON.parse(config.data));
      return [200, { search_id: "s", query: "q", results: [] }];
    });
    await client.search({ query: "q", scrape_results: true, sync: true });
    await client.search({ query: "q", scrape_results: true });
    expect(urls).toEqual(["/api/v1/search", "/api/v1/search"]);
    expect(bodies[0].sync).toBe(true);
    expect("sync" in bodies[1]).toBe(false);
  });
});
