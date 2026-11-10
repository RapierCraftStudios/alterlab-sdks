/**
 * Coverage for #37226: batchSearch accepts and forwards preset,
 * max_chars_per_result and max_total_chars (POST /api/v1/search/batch).
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchSearchRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("batchSearch response caps (#37226)", () => {
  it("forwards preset and character caps in the request body", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
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
      scrape_results: true,
      preset: "agent",
      max_chars_per_result: 2000,
      max_total_chars: 10000,
    };
    await client.batchSearch(request);

    expect(bodies[0]).toEqual(request);
  });
});
