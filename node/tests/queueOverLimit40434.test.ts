/**
 * Coverage for #40434: batchScrape accepts and forwards queue_over_limit.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("batchScrape queue_over_limit (#40434)", () => {
  it("forwards queue_over_limit in the request body", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/batch").reply((config: { data?: string }) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, { batch_id: "b1", total_urls: 1, status: "processing" }];
    });

    const request: BatchRequest = {
      urls: [{ url: "https://example.com" }],
      queue_over_limit: false,
    };
    await client.batchScrape(request);

    expect(bodies[0].queue_over_limit).toBe(false);
  });
});
