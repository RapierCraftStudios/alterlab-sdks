/**
 * Coverage for #40380: getBatchStatus / resumeBatch expose the batch
 * `paused_low_success` stop (GET /batch/{id}, POST /batch/{id}/resume).
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
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
  return { client, mock };
}

describe("batch status and resume (#40380)", () => {
  it("getBatchStatus returns paused and paused_reason", async () => {
    const { client, mock } = setup();
    mock.onGet("/api/v1/batch/b1").reply(200, {
      batch_id: "b1",
      status: "paused_low_success",
      paused: 3,
      paused_reason: { code: "low_success" },
    });
    const res = await client.getBatchStatus("b1");
    expect(res.paused).toBe(3);
    expect(res.paused_reason).toEqual({ code: "low_success" });
  });

  it("resumeBatch POSTs to the resume endpoint", async () => {
    const { client, mock } = setup();
    mock
      .onPost("/api/v1/batch/b1/resume")
      .reply(200, { batch_id: "b1", resumed: 3, status: "processing" });
    const res = await client.resumeBatch("b1");
    expect(res.resumed).toBe(3);
  });
});
