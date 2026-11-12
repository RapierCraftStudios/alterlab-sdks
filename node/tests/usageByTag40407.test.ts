/**
 * Coverage for #40407: getUsage tag filters and account tag helpers.
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

describe("usage by tag (#40407)", () => {
  it("getUsage sends tag and since only when set", async () => {
    const { client, mock } = setup();
    const seen: Record<string, unknown>[] = [];
    mock.onGet("/api/v1/usage").reply((config) => {
      seen.push(config.params ?? {});
      return [200, { balance_microcents: 1 }];
    });
    await client.getUsage();
    await client.getUsage({ tag: "sweep", since: "2026-01-01T00:00:00Z" });
    expect(seen[0]).toEqual({});
    expect(seen[1]).toEqual({ tag: "sweep", since: "2026-01-01T00:00:00Z" });
  });

  it("account.usageByTag lists tags or filters to one", async () => {
    const { client, mock } = setup();
    const seen: Array<[string, Record<string, unknown>]> = [];
    mock.onGet().reply((config) => {
      seen.push([config.url as string, config.params ?? {}]);
      return [200, {}];
    });
    await client.account.usageByTag({ since: "2026-01-01" });
    await client.account.usageByTag({ tag: "sweep" });
    expect(seen[0]).toEqual(["/api/v1/usage/tags", { since: "2026-01-01" }]);
    expect(seen[1]).toEqual(["/api/v1/usage", { tag: "sweep" }]);
  });

  it("account.setTagBudget PUTs the cap", async () => {
    const { client, mock } = setup();
    const bodies: Record<string, unknown>[] = [];
    mock.onPut("/api/v1/usage/tags/sweep").reply((config) => {
      bodies.push(JSON.parse(config.data as string));
      return [200, { tag: "sweep" }];
    });
    await client.account.setTagBudget("sweep", {
      maxSpendUsd: 16,
      expiresAt: "2026-12-01T00:00:00Z",
    });
    await client.account.setTagBudget("sweep", { maxSpendUsd: 5 });
    expect(bodies[0]).toEqual({
      max_spend_usd: 16,
      expires_at: "2026-12-01T00:00:00Z",
    });
    expect(bodies[1]).toEqual({ max_spend_usd: 5 });
  });
});
