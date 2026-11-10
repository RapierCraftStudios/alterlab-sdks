/**
 * Coverage for #39414: search response types expose `schema_version`.
 */
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  BatchSearchResponse,
  BatchSearchStatusResponse,
  SearchStatusResponse,
} from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("search schema_version (#39414)", () => {
  it("types accept schema_version and getSearch returns it", async () => {
    const client = new AlterLab({ apiKey: "sk_test_dummy", logger: silentLogger, maxRetries: 1 });
    const mock = new MockAdapter((client as any).client);
    const batch: BatchSearchResponse = {
      schema_version: "1",
      batch_id: "b",
      total_queries: 1,
      status: "processing",
      estimated_credits: 1,
      job_ids: [],
    };
    const batchStatus: Partial<BatchSearchStatusResponse> = { schema_version: "1" };
    expect(batch.schema_version).toBe("1");
    expect(batchStatus.schema_version).toBe("1");

    const body: SearchStatusResponse = {
      schema_version: "1",
      search_id: "s",
      query: "q",
      status: "completed",
      results_requested: 1,
      results_count: 1,
      completed: 1,
    };
    mock.onGet(/\/api\/v1\/search\/s$/).reply(200, body);
    const res = await client.getSearch("s");
    expect(res.schema_version).toBe("1");
  });
});

describe("ResearchJob query (#39414)", () => {
  it("accepts query", () => {
    const job: import("../src/research").ResearchJob = {
      id: "j",
      status: "queued",
      effort: "lite",
      query: "q",
      budget: {},
      cost: {},
      tool_calls: 0,
      warnings: [],
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(job.query).toBe("q");
  });
});
