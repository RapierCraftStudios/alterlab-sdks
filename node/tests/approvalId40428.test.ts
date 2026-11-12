/**
 * Coverage for #40428: `approval_id` on batchScrape and `approvalId` on crawl
 * are typed and sent on the wire only when set.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";
import type { PendingApprovalResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const PENDING: PendingApprovalResponse = {
  status: "pending_approval",
  approval_id: "apr_1",
  endpoint: "batch",
  estimated_microcents: 5_000_000,
  estimated_usd: 50,
  approval_above_usd: 10,
  approval_url: "https://alterlab.io/spend-approval/apr_1",
  expires_at: "2026-11-11T00:00:00Z",
  next_action: { type: "ask_human_to_approve" },
};

function setup() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: Record<string, unknown>[] = [];
  const reply = (config: { data?: string }) => {
    bodies.push(JSON.parse(config.data as string));
    return [202, PENDING];
  };
  mock.onPost("/api/v1/batch").reply(reply);
  mock.onPost("/api/v1/crawl").reply(reply);
  return { client, bodies };
}

describe("approval_id (#40428)", () => {
  it("batchScrape forwards approval_id", async () => {
    const { client, bodies } = setup();
    const res = (await client.batchScrape({
      urls: [{ url: "https://example.com/a" }],
      approval_id: "apr_1",
    })) as unknown as PendingApprovalResponse;
    expect(bodies[0].approval_id).toBe("apr_1");
    expect(res.status).toBe("pending_approval");
  });

  it("crawl maps approvalId to approval_id", async () => {
    const { client, bodies } = setup();
    await client.crawl({ url: "https://example.com", approvalId: "apr_1" });
    expect(bodies[0].approval_id).toBe("apr_1");
  });

  it("omits approval_id by default", async () => {
    const { client, bodies } = setup();
    await client.batchScrape([{ url: "https://example.com/a" }]);
    await client.crawl({ url: "https://example.com" });
    expect(bodies.every((b) => !("approval_id" in b))).toBe(true);
  });
});
