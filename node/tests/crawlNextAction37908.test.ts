/**
 * Coverage for #37908: `getCrawl` must expose the API's `next_action` field
 * on `CrawlStatusResponse` (typed), and tolerate its absence.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, CrawlStatusResponse } from "../src/index";

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    maxRetries: 1,
    retryDelay: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

const base = {
  crawl_id: "c1",
  status: "partial",
  total: 2,
  completed: 1,
  failed: 1,
  in_progress: 0,
  credits_debited: 1,
  created_at: "2026-01-01T00:00:00Z",
  current_depth: 1,
  max_depth: 1,
  total_discovered: 2,
};

describe("getCrawl next_action", () => {
  it("returns a typed next_action", async () => {
    const { client, mock } = makeClient();
    mock.onGet(/\/api\/v1\/crawl\/c1/).reply(200, {
      ...base,
      next_action: {
        type: "retry",
        params: { tier: 3 },
        price_microcents: 5,
        docs_url: "https://x",
      },
    });
    const res: CrawlStatusResponse = await client.getCrawl("c1");
    expect(res.next_action?.type).toBe("retry");
    expect(res.next_action?.price_microcents).toBe(5);
  });

  it("leaves next_action undefined when absent", async () => {
    const { client, mock } = makeClient();
    mock.onGet(/\/api\/v1\/crawl\/c1/).reply(200, base);
    const res = await client.getCrawl("c1");
    expect(res.next_action).toBeUndefined();
  });
});
