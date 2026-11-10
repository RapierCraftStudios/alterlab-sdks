/**
 * Coverage for #38895: Node SDK research methods map onto /api/v1/research.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, parseSseEvents } from "../src/index";

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

describe("research (#38895)", () => {
  it("posts the request body to /api/v1/research", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/research").reply((config) => {
      body = JSON.parse(config.data);
      return [202, { id: "j1", status: "queued" }];
    });
    const job = await client.research({
      query: "q",
      effort: "deep",
      max_cost_microcents: 5,
    });
    expect(job.id).toBe("j1");
    expect(body).toEqual({
      query: "q",
      effort: "deep",
      max_cost_microcents: 5,
    });
  });

  it("waitForResearch polls until settled and times out otherwise", async () => {
    const { client, mock } = makeClient();
    const states = ["queued", "running", "completed_partial"];
    mock
      .onGet("/api/v1/research/j1")
      .reply(() => [200, { id: "j1", status: states.shift() }]);
    const job = await client.waitForResearch("j1", { pollIntervalMs: 1 });
    expect(job.status).toBe("completed_partial");
    expect(states).toHaveLength(0);

    mock
      .onGet("/api/v1/research/j2")
      .reply(200, { id: "j2", status: "running" });
    await expect(
      client.waitForResearch("j2", { pollIntervalMs: 1, timeoutMs: 5 }),
    ).rejects.toThrow(/still running/);

    mock
      .onGet("/api/v1/research/j3")
      .reply(200, { id: "j3", status: "awaiting_approval" });
    expect((await client.waitForResearch("j3")).status).toBe(
      "awaiting_approval",
    );
  });

  it("cancel, plan and approve use the documented paths", async () => {
    const { client, mock } = makeClient();
    mock
      .onPost("/api/v1/research/j1/cancel")
      .reply(200, { status: "cancelled" });
    mock.onGet("/api/v1/research/j1/plan").reply(200, { steps: [] });
    mock
      .onPut("/api/v1/research/j1/plan")
      .reply((c) => [200, JSON.parse(c.data)]);
    let approveData: unknown = "unset";
    mock.onPost("/api/v1/research/j1/approve").reply((c) => {
      approveData = c.data;
      return [200, { status: "queued" }];
    });
    expect((await client.cancelResearch("j1")).status).toBe("cancelled");
    expect(await client.getResearchPlan("j1")).toEqual({ steps: [] });
    expect(await client.updateResearchPlan("j1", { steps: ["a"] })).toEqual({
      plan: { steps: ["a"] },
    });
    await client.approveResearch("j1");
    expect(approveData).toBeUndefined();
    await client.approveResearch("j1", { steps: ["b"] });
    expect(JSON.parse(approveData as string)).toEqual({
      plan: { steps: ["b"] },
    });
  });

  it("researchEvents parses SSE and sends Last-Event-ID", async () => {
    const { client, mock } = makeClient();
    let header: unknown;
    mock.onGet("/api/v1/research/j1/events").reply((config) => {
      header = config.headers?.["Last-Event-ID"];
      return [
        200,
        'id: 1\nevent: status\ndata: {"status":"running"}\n\n: ka\n\nid: 2\nevent: research.completed\ndata: {"status":"completed"}\n\n',
      ];
    });
    const events = await client.researchEvents("j1", "0");
    expect(header).toBe("0");
    expect(events.map((e) => [e.id, e.event])).toEqual([
      ["1", "status"],
      ["2", "research.completed"],
    ]);
    expect(events[1].data).toEqual({ status: "completed" });
  });

  it("parseSseEvents keeps non-JSON data as text", () => {
    expect(parseSseEvents("event: x\ndata: hello\n\n")).toEqual([
      { event: "x", data: "hello" },
    ]);
  });
});
