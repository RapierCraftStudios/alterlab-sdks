/**
 * Coverage for #31823: the server's sync-poll-timeout downgrade
 * (`202 { job_id, sync_downgraded: true }`, replacing the old `504`) must
 * not be mistaken for a completed scrape, and `waitForJob` must resolve a
 * job whose terminal status is the canonical `"succeeded"` value (not the
 * legacy `"completed"` the SDK previously hardcoded).
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, JobFailedError } from "../src/index";

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    maxRetries: 1,
    retryDelay: 1,
  });
  // `client` is a private field at compile time only — reach in at runtime
  // to attach the mock adapter to the underlying axios instance.
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

describe("scrape() 202 sync-downgrade handling", () => {
  it("polls through a sync_downgraded 202 and returns the real result, not the envelope", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-downgrade-1";

    mock.onPost("/api/v1/scrape").reply(202, {
      job_id: jobId,
      sync_downgraded: true,
      reason: "Request exceeded the 85s synchronous window",
      poll_url: `/api/v1/jobs/${jobId}`,
    });

    mock
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "queued" })
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, {
        job_id: jobId,
        status: "succeeded",
        result: { url: "https://example.com", content: "real scraped content" },
      });

    const result = await client.scrape({
      url: "https://example.com",
      // Default sync=true (omitted) — the request never opted into async.
    });

    expect(result).toEqual({
      url: "https://example.com",
      content: "real scraped content",
    });
    expect(
      (result as { sync_downgraded?: boolean }).sync_downgraded,
    ).toBeUndefined();
  });

  it("returns the async envelope as-is when sync: false was explicit", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-async-1";

    mock.onPost("/api/v1/scrape").reply(202, { job_id: jobId });

    const result = await client.scrape({
      url: "https://example.com",
      sync: false,
    });

    expect((result as { job_id?: string }).job_id).toBe(jobId);
    // No polling should have happened for an explicit async request.
    expect(mock.history.get.length).toBe(0);
  });

  it("serializes wait_until_deadline and keeps sync enabled", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply((config) => {
      const data = JSON.parse(config.data as string) as Record<string, unknown>;
      expect(data.sync).toBe(true);
      expect(data.sync_policy).toBe("wait_until_deadline");
      return [200, { status_code: 200, content: {} }];
    });

    const result = await client.scrape({
      url: "https://example.com",
      sync: true,
      sync_policy: "wait_until_deadline",
    });

    expect(result.status_code).toBe(200);
  });

  it("rejects wait_until_deadline with sync=false before making a request", async () => {
    const { client, mock } = makeClient();

    await expect(
      client.scrape({
        url: "https://example.com",
        sync: false,
        sync_policy: "wait_until_deadline",
      }),
    ).rejects.toThrow("requires sync=true");
    expect(mock.history.post.length).toBe(0);
  });
});

describe("waitForJob() status vocabulary", () => {
  it("resolves on the canonical 'succeeded' terminal status", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-succeeded-1";

    mock.onGet(`/api/v1/jobs/${jobId}`).reply(200, {
      job_id: jobId,
      status: "succeeded",
      result: { url: "https://example.com", content: "ok" },
    });

    const job = await client.waitForJob(jobId, { pollInterval: 1 });
    expect(job.status).toBe("succeeded");
    expect(job.result).toEqual({ url: "https://example.com", content: "ok" });
  });

  it("continues polling through 'queued' and 'retrying' before resolving", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-queued-1";

    mock
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "queued" })
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "retrying" })
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "succeeded", result: {} });

    const job = await client.waitForJob(jobId, { pollInterval: 1 });
    expect(job.status).toBe("succeeded");
  });

  it.each(["failed", "rejected", "cancelled"] as const)(
    "throws JobFailedError on terminal status '%s'",
    async (status) => {
      const { client, mock } = makeClient();
      const jobId = `job-${status}-1`;

      mock
        .onGet(`/api/v1/jobs/${jobId}`)
        .reply(200, { job_id: jobId, status, error: "boom" });

      await expect(
        client.waitForJob(jobId, { pollInterval: 1 }),
      ).rejects.toThrow(JobFailedError);
    },
  );

  // #31889: the fix that added the canonical/new statuses above (`queued`,
  // `retrying`, `succeeded`, `rejected`, `cancelled`) explicitly preserves
  // the legacy `completed` success alias and the original `pending`/`running`
  // in-progress statuses (see `_JOB_STATUS_SUCCEEDED`/status checks in
  // `waitForJob`) — neither branch had a test until now.
  it("resolves on the legacy 'completed' terminal status", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-completed-1";

    mock.onGet(`/api/v1/jobs/${jobId}`).reply(200, {
      job_id: jobId,
      status: "completed",
      result: { url: "https://example.com", content: "legacy ok" },
    });

    const job = await client.waitForJob(jobId, { pollInterval: 1 });
    expect(job.status).toBe("completed");
    expect(job.result).toEqual({
      url: "https://example.com",
      content: "legacy ok",
    });
  });

  it("continues polling through the legacy 'pending' and 'running' statuses", async () => {
    const { client, mock } = makeClient();
    const jobId = "job-pending-1";

    mock
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "pending" })
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "running" })
      .onGet(`/api/v1/jobs/${jobId}`)
      .replyOnce(200, { job_id: jobId, status: "succeeded", result: {} });

    const job = await client.waitForJob(jobId, { pollInterval: 1 });
    expect(job.status).toBe("succeeded");
  });
});
