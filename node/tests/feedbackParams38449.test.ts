/**
 * Coverage for #38449: Node SDK feedback() sends tool_name and url.
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

describe("feedback tool_name/url (#38449)", () => {
  it("sends toolName and url as wire fields", async () => {
    const body = await send({
      category: "blocked",
      happened: "empty body",
      toolName: "scrape",
      url: "https://example.com/p",
    });
    expect(body).toEqual({
      what_failed: "[blocked] empty body",
      surface: "sdk",
      tool_name: "scrape",
      url: "https://example.com/p",
    });
  });

  it("omits them when unset", async () => {
    const body = await send({ category: "other", happened: "x" });
    expect(body).not.toHaveProperty("tool_name");
    expect(body).not.toHaveProperty("url");
  });

  it("truncates to 100 and 2000 characters", async () => {
    const body = await send({
      category: "other",
      happened: "x",
      toolName: "t".repeat(150),
      url: "https://e.com/" + "a".repeat(3000),
    });
    expect((body.tool_name as string).length).toBe(100);
    expect((body.url as string).length).toBe(2000);
  });
});
