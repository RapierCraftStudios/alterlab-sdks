/**
 * Coverage for #39043: `cache_reason` is typed on ScrapeResponse and
 * surfaced from the API response.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, ScrapeResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("cache_reason on scrape (#39043)", () => {
  it("scrape surfaces cache_reason", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const reason = "max_age=3600 from request";
    mock.onPost("/api/v1/scrape").reply(200, {
      url: "https://example.com",
      status_code: 200,
      cached: true,
      cache_reason: reason,
    });
    const res: ScrapeResponse = await client.scrape({
      url: "https://example.com",
    });
    const r: string | null | undefined = res.cache_reason;
    expect(r).toBe(reason);
  });
});
