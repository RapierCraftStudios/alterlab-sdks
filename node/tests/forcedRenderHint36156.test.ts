/**
 * #36156: the SDK exposes the API's forced-render retry hint (`error.hint`)
 * on failed sync scrapes, failed polled jobs and crawl page errors.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, JobFailedError, getErrorHint } from "../src/index";

const HINT = {
  code: "render_js_auto",
  reason: "challenge",
  message:
    "This request forced browser rendering and the page returned a verification " +
    'screen instead of content. Retrying with render_js="auto" lets the platform ' +
    "start at the lowest tier that returns the page.",
};

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

async function caught(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
  } catch (e) {
    return e;
  }
  throw new Error("expected rejection");
}

describe("forced-render hint (#36156)", () => {
  it("reads the hint from a failed sync scrape (422 body)", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(422, {
      detail: "anti_bot_blocked: Blocked",
      error: { error_code: "anti_bot_blocked", message: "Blocked", hint: HINT },
    });
    const err = await caught(
      client.scrape({ url: "https://example.com", render_js: true }),
    );
    expect(getErrorHint(err)).toEqual(HINT);
  });

  it("returns null for a 422 without a hint", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(422, {
      detail: "anti_bot_blocked: Blocked",
      error: { error_code: "anti_bot_blocked", message: "Blocked" },
    });
    const err = await caught(client.scrape({ url: "https://example.com" }));
    expect(getErrorHint(err)).toBeNull();
  });

  it("sets JobFailedError.hint from a failed polled job", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/jobs/job-hint-1").reply(200, {
      job_id: "job-hint-1",
      status: "failed",
      error: { code: "TIMEOUT", message: "Job exceeded timeout", hint: HINT },
    });
    const err = await caught(
      client.waitForJob("job-hint-1", { pollInterval: 1 }),
    );
    expect(err).toBeInstanceOf(JobFailedError);
    expect((err as JobFailedError).hint).toEqual(HINT);
    expect(getErrorHint(err)).toEqual(HINT);
    expect((err as Error).message).toBe(
      "Job job-hint-1 ended with status 'failed': Job exceeded timeout",
    );
  });

  it("keeps string job errors unchanged and hint null", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/jobs/job-2").reply(200, {
      job_id: "job-2",
      status: "failed",
      error: "plain failure",
    });
    const err = (await caught(
      client.waitForJob("job-2", { pollInterval: 1 }),
    )) as JobFailedError;
    expect(err.message).toBe("Job job-2 ended with status 'failed': plain failure");
    expect(err.hint).toBeNull();
  });

  it("JobFailedError stays constructible with three arguments", () => {
    const err = new JobFailedError("job-3", "failed", "detail");
    expect(err.hint).toBeNull();
  });

  it("reads the hint from a crawl page error object", () => {
    const page = { url: "https://example.com/a", error: { hint: HINT } };
    expect(getErrorHint(page.error)).toEqual(HINT);
  });

  it.each([
    [null],
    ["string error"],
    [{}],
    [{ hint: "not-an-object" }],
    [{ hint: { code: "render_js_auto" } }],
    [{ hint: { message: "missing code" } }],
    [{ hint: { code: 1, message: "bad code type" } }],
  ])("returns null for absent or malformed hint %#", (error) => {
    expect(getErrorHint(error)).toBeNull();
  });

  it("drops unknown hint keys", () => {
    expect(getErrorHint({ hint: { ...HINT, internal: "x" } })).toEqual(HINT);
  });
});
