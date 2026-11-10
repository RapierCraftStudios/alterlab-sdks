/**
 * Coverage for #39751: ScrapeResponse.revalidated (added by #39687) is typed
 * on the Node SDK response.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, ScrapeResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("ScrapeResponse.revalidated (#39751)", () => {
  it("surfaces revalidated from the scrape response", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    mock.onPost("/api/v1/scrape").reply(200, {
      url: "https://example.com",
      status_code: 200,
      content: "ok",
      headers: {},
      cached: true,
      revalidated: true,
      credits_used: 1,
      response_time_ms: 5,
    });
    const res: ScrapeResponse = await client.scrape({
      url: "https://example.com",
    });
    const flag: boolean | undefined = res.revalidated;
    expect(flag).toBe(true);
  });
});
