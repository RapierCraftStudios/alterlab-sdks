/**
 * Coverage for #40385: batchScrape accepts and forwards max_in_flight_per_domain.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("batchScrape max_in_flight_per_domain (#40385)", () => {
  it("forwards the per-domain cap in the request body", async () => {
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
      max_in_flight_per_domain: 2,
    };
    await client.batchScrape(request);

    expect(bodies[0].max_in_flight_per_domain).toBe(2);
  });
});
