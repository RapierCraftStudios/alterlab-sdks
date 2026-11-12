/**
 * Coverage for #40384: `BatchRequest.max_in_flight_per_domain` is typed and
 * sent on the wire to POST /api/v1/batch.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("batchScrape max_in_flight_per_domain (#40384)", () => {
  it("sends max_in_flight_per_domain in the request body", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/batch").reply((config) => {
      bodies.push(JSON.parse(config.data));
      return [202, { batch_id: "b1", job_ids: [], status: "queued" }];
    });

    const request: BatchRequest = {
      urls: [{ url: "https://example.com/a" }],
      max_in_flight_per_domain: 3,
    };
    await client.batchScrape(request);

    expect(bodies).toHaveLength(1);
    expect(bodies[0].max_in_flight_per_domain).toBe(3);
  });
});
