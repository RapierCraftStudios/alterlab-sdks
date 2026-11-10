/**
 * Coverage for #39080: Node SDK feedback() sends suggestion.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

async function send(request: Parameters<AlterLab["feedback"]>[0]) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  let body: Record<string, unknown> = {};
  mock.onPost("/api/v1/agent/feedback").reply((config) => {
    body = JSON.parse(config.data);
    return [200, { report_id: "a", cluster_key: "k", status: "received" }];
  });
  await client.feedback(request);
  return body;
}

describe("feedback suggestion (#39080)", () => {
  it("sends suggestion as a wire field", async () => {
    const body = await send({
      category: "other",
      happened: "x",
      suggestion: "add a dry-run flag",
    });
    expect(body.suggestion).toBe("add a dry-run flag");
  });

  it("omits it when unset", async () => {
    const body = await send({ category: "other", happened: "x" });
    expect(body).not.toHaveProperty("suggestion");
  });

  it("truncates to 1000 characters", async () => {
    const body = await send({
      category: "other",
      happened: "x",
      suggestion: "s".repeat(1500),
    });
    expect((body.suggestion as string).length).toBe(1000);
  });
});
