/**
 * Coverage for #36243: ScrapeRequest.cost_controls exposes the API's opt-in
 * `fallback_on_block` and the SDK sends it unchanged.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("scrape cost_controls.fallback_on_block (#36243)", () => {
  it("sends fallback_on_block in cost_controls", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/scrape").reply((config: { data?: string }) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [422, { detail: "anti_bot_blocked: Blocked" }];
    });

    await expect(
      client.scrape({
        url: "https://example.com",
        cost_controls: { force_tier: "4", fallback_on_block: true },
      }),
    ).rejects.toBeDefined();

    expect(bodies[0].cost_controls).toEqual({
      force_tier: "4",
      fallback_on_block: true,
    });
  });
});
