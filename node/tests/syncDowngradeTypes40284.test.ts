/**
 * #40284: `scrape({ sync: false })` is typed as the accepted-job envelope
 * (overload), the default stays `ScrapeResponse`, and a poll timeout raises
 * a typed `JobTimeoutError` carrying the job id and poll URL.
 */
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  JobTimeoutError,
  ScrapeAcceptedResponse,
  ScrapeResponse,
  SyncDowngradedResponse,
} from "../src/index";

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

type IsExact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

describe("scrape() overloads (#40284)", () => {
  it("narrows sync:false to ScrapeAcceptedResponse and the default to ScrapeResponse", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(202, {
      job_id: "job-1",
      poll_url: "/api/v1/jobs/job-1",
    });

    const accepted = await client.scrape({
      url: "https://example.com",
      sync: false,
    });
    const typedAccepted: IsExact<typeof accepted, ScrapeAcceptedResponse> =
      true;
    expect(typedAccepted).toBe(true);
    // Envelope is returned unchanged (#31888 semantics).
    expect(accepted.job_id).toBe("job-1");

    mock.reset();
    mock.onPost("/api/v1/scrape").reply(200, {
      url: "https://example.com",
      content: "ok",
    });
    const done = await client.scrape({ url: "https://example.com" });
    const typedDone: IsExact<typeof done, ScrapeResponse> = true;
    expect(typedDone).toBe(true);
  });

  it("exposes the SyncDowngradedResponse envelope type", () => {
    const env: SyncDowngradedResponse = {
      job_id: "j",
      sync_downgraded: true,
      reason: "Runtime escalation beyond tier 2; job is still processing.",
      credits_status: "held_pending_completion",
    };
    expect(env.sync_downgraded).toBe(true);
  });

  it("keeps an explicit result:null from a followed downgrade", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(202, {
      job_id: "job-n",
      sync_downgraded: true,
    });
    mock
      .onGet("/api/v1/jobs/job-n")
      .reply(200, { job_id: "job-n", status: "succeeded", result: null });
    const result = await client.scrape({ url: "https://example.com" });
    expect(result).toBeNull();
  });
});

describe("waitForJob timeout (#40284)", () => {
  it("throws JobTimeoutError with jobId and pollUrl (still an Error)", async () => {
    const { client, mock } = makeClient();
    mock
      .onGet("/api/v1/jobs/job-slow")
      .reply(200, { job_id: "job-slow", status: "running" });

    let caught: unknown;
    try {
      await client.waitForJob("job-slow", {
        pollInterval: 1,
        pollTimeout: 5,
        maxInterval: 1,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(JobTimeoutError);
    expect(caught).toBeInstanceOf(Error);
    const err = caught as JobTimeoutError;
    expect(err.jobId).toBe("job-slow");
    expect(err.pollUrl).toBe("/api/v1/jobs/job-slow");
    expect(err.message).toContain("did not complete within");
  });
});
