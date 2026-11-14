/** Coverage for #40690: `suggestions` opt-out and typed result field. */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, RecurringSuggestion, ScrapeResponse } from "../src/index";

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

const suggestion: RecurringSuggestion = {
  type: "schedule",
  reason: "6 similar pages",
  tool: "alterlab_schedule",
  endpoint: "POST /api/v1/schedules",
  create: {
    name: "Re-scrape e.com",
    urls: ["https://e.com/1"],
    cron: "0 9 * * *",
  },
  estimated_run_cost_microcents: 1000,
  estimated_monthly_cost_microcents: 30000,
  docs_url: "https://alterlab.io/docs",
};

describe("recurring suggestions (#40690)", () => {
  it("forwards suggestions=false and exposes the typed field", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [
        200,
        {
          content: "hi",
          status_code: 200,
          url: "https://e.com/1",
          suggestions: [suggestion],
        },
      ];
    });
    const res = (await client.scrape({
      url: "https://e.com/1",
      suggestions: false,
    })) as ScrapeResponse;
    expect(body.suggestions).toBe(false);
    expect(res.suggestions?.[0].create.cron).toBe("0 9 * * *");
  });

  it("omits suggestions by default", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { content: "hi", status_code: 200, url: "https://e.com/1" }];
    });
    await client.scrape({ url: "https://e.com/1" });
    expect("suggestions" in body).toBe(false);
  });
});
