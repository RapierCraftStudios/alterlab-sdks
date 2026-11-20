/**
 * #41159: JobFailedError carries the #40689 failure envelope.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, JobFailedError } from "../src/index";

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

async function failure(
  client: AlterLab,
  jobId: string,
): Promise<JobFailedError> {
  try {
    await client.waitForJob(jobId, { pollInterval: 1 });
  } catch (e) {
    return e as JobFailedError;
  }
  throw new Error("expected waitForJob to throw");
}

describe("JobFailedError carries the failure envelope", () => {
  it("exposes every envelope field unchanged", async () => {
    const { client, mock } = makeClient();
    const nextAction = { type: "wait", params: { retry_after: 30 } };
    mock.onGet("/api/v1/jobs/j1").reply(200, {
      job_id: "j1",
      status: "failed",
      error: {
        message: "origin down",
        error_code: "origin_unreachable",
        retryable: false,
        charged: false,
        auto_retry: "none",
        retry_after_s: 30,
        next_action: nextAction,
      },
    });
    const err = await failure(client, "j1");
    expect(err).toBeInstanceOf(JobFailedError);
    expect(err.code).toBe("origin_unreachable");
    expect(err.errorCode).toBe("origin_unreachable");
    expect(err.retryable).toBe(false);
    expect(err.charged).toBe(false);
    expect(err.autoRetry).toBe("none");
    expect(err.retryAfterSeconds).toBe(30);
    expect(err.nextAction).toEqual(nextAction);
  });

  it("reads a job-level next_action and retryable=true", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/jobs/j2").reply(200, {
      job_id: "j2",
      status: "failed",
      error: {
        message: "x",
        error_code: "origin_unavailable",
        retryable: true,
      },
      next_action: { type: "retry" },
    });
    const err = await failure(client, "j2");
    expect(err.retryable).toBe(true);
    expect(err.nextAction).toEqual({ type: "retry" });
  });

  it("keeps the old defaults for a string error", async () => {
    const { client, mock } = makeClient();
    mock
      .onGet("/api/v1/jobs/j3")
      .reply(200, { job_id: "j3", status: "failed", error: "boom" });
    const err = await failure(client, "j3");
    expect(err.code).toBe("job_failed");
    expect(err.errorCode).toBeNull();
    expect(err.retryable).toBe(false);
    expect(err.retryAfterSeconds).toBeNull();
    expect(err.charged).toBeNull();
    expect(err.autoRetry).toBeNull();
    expect(err.nextAction).toBeNull();
  });
});
