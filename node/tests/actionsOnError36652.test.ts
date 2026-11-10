/**
 * #36652: the SDK forwards `actions_on_error` and per-action `optional` /
 * `timeout_ms`, and types `actions_status` plus `action_results[].duration_ms`.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, type ScrapeResponse } from "../src/index";

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

const OK = {
  url: "https://example.com",
  status_code: 200,
  content: { markdown: "ok" },
  action_results: [
    {
      index: 0,
      type: "click",
      success: false,
      error: "timeout",
      duration_ms: 500,
    },
  ],
  actions_status: "partial",
};

describe("actions_on_error (#36652)", () => {
  it("forwards actions_on_error and per-action fields", async () => {
    const { client, mock } = makeClient();
    let body: { advanced: Record<string, unknown> } = { advanced: {} };
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [200, OK];
    });
    const res: ScrapeResponse = await client.scrape({
      url: "https://example.com",
      render_js: true,
      actions: [
        { type: "click", selector: "#a", optional: false, timeout_ms: 500 },
      ],
      actions_on_error: "abort",
    });
    expect(body.advanced.actions_on_error).toBe("abort");
    expect((body.advanced.actions as object[])[0]).toMatchObject({
      optional: false,
      timeout_ms: 500,
    });
    expect(res.actions_status).toBe("partial");
    expect(res.action_results?.[0].duration_ms).toBe(500);
  });

  it("omits actions_on_error when unset", async () => {
    const { client, mock } = makeClient();
    let body: { advanced: Record<string, unknown> } = { advanced: {} };
    mock.onPost("/api/v1/scrape").reply((config) => {
      body = JSON.parse(config.data);
      return [200, OK];
    });
    await client.scrape({
      url: "https://example.com",
      render_js: true,
      actions: [{ type: "click", selector: "#a" }],
    });
    expect(body.advanced).not.toHaveProperty("actions_on_error");
  });
});
