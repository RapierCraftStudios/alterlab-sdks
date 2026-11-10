/**
 * Coverage for #38455: Node SDK feedback() sends `surface`.
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

describe("feedback surface (#38455)", () => {
  it("defaults surface to sdk", async () => {
    const body = await send({ category: "other", happened: "x" });
    expect(body.surface).toBe("sdk");
  });

  it("honours an explicit surface", async () => {
    const body = await send({
      category: "other",
      happened: "x",
      surface: "mcp",
    });
    expect(body.surface).toBe("mcp");
  });
});
