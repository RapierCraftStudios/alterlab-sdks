/**
 * Coverage for #39413: batchSearch forwards localization, cache, webhook-secret and
 * zero-retention params; extract forwards saved-template id/version.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchSearchRequest, ExtractRequest } from "../src/index";

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

describe("SDK param parity (#39413)", () => {
  it("batchSearch forwards the new request fields", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/search/batch").reply((config: { data?: string }) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [
        200,
        {
          batch_id: "b1",
          total_queries: 1,
          status: "queued",
          estimated_credits: 1,
          job_ids: ["j1"],
        },
      ];
    });

    const request: BatchSearchRequest = {
      queries: ["alpha"],
      country: "gb",
      city: "London",
      coordinates: { lat: 51.5, lng: -0.12, radius_km: 25 },
      device: "tablet",
      no_cache: true,
      uule: "w+CAIQICIGTG9uZG9u",
      webhook_url: "https://example.com/hook",
      webhook_secret: "0123456789abcdef",
      zero_data_retention: true,
      zero_trace: true,
    };
    await client.batchSearch(request);

    expect(bodies[0]).toEqual(request);
  });

  it("extract forwards extraction_template_id and extraction_template_version", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/extract").reply((config: { data?: string }) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, { data: {} }];
    });

    const request: ExtractRequest = {
      content: "<p>hi</p>",
      extraction_template_id: "3f1c2b4a-0000-4000-8000-000000000000",
      extraction_template_version: 2,
    };
    await client.extract(request);

    expect(bodies[0]).toEqual(request);
  });
});
