/**
 * Coverage for #38418: Node SDK feedback() payload mapping and status URL.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

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

describe("feedback (#38418)", () => {
  it("maps fields and returns statusUrl", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/agent/feedback").reply((config) => {
      body = JSON.parse(config.data);
      return [
        200,
        { report_id: "afb_1", cluster_key: "ck1", status: "received" },
      ];
    });
    const res = await client.feedback({
      category: "blocked",
      tried: "mode=auto",
      happened: "empty body",
      expected: "html",
      jobId: "job_9",
    });
    expect(body).toEqual({
      what_failed: "[blocked] empty body",
      what_tried: "mode=auto job_id=job_9",
      surface: "sdk",
      what_expected: "html",
    });
    expect(res.cluster_key).toBe("ck1");
    expect(res.statusUrl).toBe(
      "https://api.alterlab.io/api/v1/agent/feedback/ck1",
    );
  });

  it("truncates and omits empty optional fields", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/agent/feedback").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { report_id: "a", cluster_key: "k", status: "received" }];
    });
    await client.feedback({ category: "bug", happened: "x".repeat(2000) });
    expect((body.what_failed as string).length).toBe(1000);
    expect(body).not.toHaveProperty("what_tried");
    expect(body).not.toHaveProperty("what_expected");
  });

  it("lets explicit what_* wire fields override derived values", async () => {
    const { client, mock } = makeClient();
    let body: Record<string, unknown> = {};
    mock.onPost("/api/v1/agent/feedback").reply((config) => {
      body = JSON.parse(config.data);
      return [200, { report_id: "a", cluster_key: "k", status: "received" }];
    });
    await client.feedback({
      category: "blocked",
      happened: "ignored",
      tried: "ignored",
      expected: "ignored",
      what_failed: "f".repeat(2000),
      what_tried: "t",
      what_expected: "e",
    });
    expect((body.what_failed as string).length).toBe(1000);
    expect(body.what_tried).toBe("t");
    expect(body.what_expected).toBe("e");
  });
});
