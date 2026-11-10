import { AlterLab } from "../src";

function make(
  onUnexpectedResponse?: (i: unknown) => void,
  data: unknown = { ok: true },
) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    onUnexpectedResponse,
  });
  const calls: any[] = [];
  (client as any).client.request = jest.fn(async (config: any) => {
    calls.push(config);
    return { status: 200, headers: {}, data };
  });
  return { client, calls };
}

describe("MCP parity namespaces (#40286)", () => {
  it("support.ticket and jobs.report post the documented bodies", async () => {
    const { client, calls } = make();
    await client.support.ticket({ subject: "Broken", body: "b", jobId: "j1" });
    await client.jobs.report("j1", "blocked", { description: "d" });
    await client.reportScrape("j2", "wrong_content");
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/agent/support-ticket",
      "/api/v1/feedback/scrape",
      "/api/v1/feedback/scrape",
    ]);
    expect(calls[0].data).toEqual({
      subject: "Broken",
      body: "b",
      on_behalf_of_user: true,
      job_id: "j1",
    });
    expect(calls[1].data).toEqual({
      job_id: "j1",
      issue_type: "blocked",
      description: "d",
    });
    expect(() => client.jobs.report("j1", "nope" as any)).toThrow(/issueType/);
  });

  it("read methods hit the expected routes", async () => {
    const { client, calls } = make();
    await client.account.balance();
    await client.pricing();
    await client.news({ q: "ai", limit: 3 });
    await client.store.get("a/b");
    await client.aiVisibility("status", { runId: "r1" });
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["GET", "/api/v1/billing/balance"],
      ["GET", "/api/v1/pricing"],
      ["GET", "/api/v1/news"],
      ["GET", "/api/v1/listings/a%2Fb"],
      ["GET", "/api/v1/ai-visibility/runs/r1"],
    ]);
    expect(calls[2].params).toEqual({ q: "ai", limit: 3 });
  });

  it("onUnexpectedResponse is opt-in and only notifies", async () => {
    const quiet = make(undefined, "<html>");
    await quiet.client.pricing();
    expect(quiet.calls).toHaveLength(1);
    const events: unknown[] = [];
    const loud = make((i) => events.push(i), "<html>");
    await loud.client.pricing();
    expect(loud.calls).toHaveLength(1);
    expect(events).toEqual([
      { method: "GET", path: "/api/v1/pricing", reason: "not a JSON object" },
    ]);
  });
});
