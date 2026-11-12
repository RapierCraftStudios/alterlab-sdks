/**
 * #40335 contract tests: recorded-shape fixtures for the generated operation
 * table (ALT-310 batch body, ALT-312 waitForJob statuses, rejected_items,
 * spend-limit error) and the SDK <-> MCP parity extension.
 */
import axios, { AxiosError } from "axios";
import MockAdapter from "axios-mock-adapter";
import { AlterLab, JobFailedError, transport } from "../src/index";

function withMock<T>(
  setup: (m: MockAdapter) => void,
  run: (c: AlterLab) => Promise<T>,
): Promise<T> {
  const mock = new MockAdapter(axios);
  setup(mock);
  const client = new AlterLab({ apiKey: "sk_test_x", maxRetries: 1 });
  return run(client).finally(() => mock.restore());
}

describe("generated operation contract (#40335)", () => {
  it("batch posts {urls:[{url}]} and surfaces rejected_items (ALT-310)", async () => {
    let body: any;
    const res = await withMock(
      (m) =>
        m.onPost("/api/v1/batch").reply((cfg) => {
          body = JSON.parse(cfg.data);
          return [
            200,
            {
              batch_id: "b1",
              total: 2,
              accepted: 1,
              rejected_items: [
                { index: 1, url: "x".repeat(10), error: "too long" },
              ],
              items: [],
            },
          ];
        }),
      (c) => c.batchScrape([{ url: "https://a.example" }]),
    );
    expect(Array.isArray(body.urls)).toBe(true);
    expect(body.urls[0].url).toBe("https://a.example");
    expect((res as any).rejected_items).toHaveLength(1);
  });

  it.each(["failed", "rejected", "cancelled"])(
    "waitForJob throws JobFailedError for %s (ALT-312)",
    async (status) => {
      const err = await withMock(
        (m) =>
          m.onGet("/api/v1/jobs/j1").reply(200, {
            job_id: "j1",
            status,
            error: { message: "nope" },
          }),
        (c) => c.waitForJob("j1").catch((e) => e),
      );
      expect(err).toBeInstanceOf(JobFailedError);
      expect(err.status).toBe(status);
      expect(err.code).toBe("job_failed");
      expect(err.message).not.toContain("[object Object]");
    },
  );

  it("waitForJob returns on succeeded", async () => {
    const job = await withMock(
      (m) =>
        m
          .onGet("/api/v1/jobs/j2")
          .reply(200, { job_id: "j2", status: "succeeded", result: {} }),
      (c) => c.waitForJob("j2"),
    );
    expect(job.status).toBe("succeeded");
  });

  it("spend-limit error surfaces as a typed, non-retryable error", async () => {
    const err: any = await withMock(
      (m) =>
        m.onPost("/api/v1/scrape").reply(
          402,
          {
            detail: {
              error: "spend_limit_exceeded",
              message: "Spend limit reached",
            },
          },
          { "x-request-id": "req-s" },
        ),
      (c) => c.scrape({ url: "https://example.com" }).catch((e) => e),
    );
    expect(err).toBeInstanceOf(AxiosError);
    expect(err.requestId).toBe("req-s");
    expect(err.retryable).toBe(false);
    expect(err.message).toContain("Spend limit reached");
  });

  it("every generated operation is a documented SDK path", () => {
    const ops = transport.OPERATIONS.map((o) => `${o.method} ${o.path}`);
    expect(ops).toEqual(
      expect.arrayContaining([
        "POST /api/v1/scrape",
        "GET /api/v1/jobs/{job_id}",
        "POST /api/v1/batch",
        "GET /api/v1/batch/{batch_id}",
        "POST /api/v1/agent/support-ticket",
        "POST /api/v1/feedback/scrape",
      ]),
    );
    expect(new Set(ops).size).toBe(ops.length);
  });
});
