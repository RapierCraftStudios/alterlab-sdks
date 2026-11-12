/**
 * Coverage for #40444: getUsage sends X-Organization-Id only when
 * `organizationId` is set; tag/since query params are unchanged.
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
  const seen: { headers: Record<string, unknown>; params: unknown }[] = [];
  mock.onGet("/api/v1/usage").reply((config) => {
    seen.push({
      headers: config.headers as Record<string, unknown>,
      params: config.params,
    });
    return [200, {}];
  });
  return { client, seen };
}

describe("getUsage organizationId (#40444)", () => {
  it("sends X-Organization-Id when set", async () => {
    const { client, seen } = setup();
    await client.getUsage({ organizationId: "org_1" });
    expect(seen[0].headers["X-Organization-Id"]).toBe("org_1");
  });

  it("omits the header when not set and keeps tag/since params", async () => {
    const { client, seen } = setup();
    await client.getUsage({ tag: "t1", since: "2026-01-01T00:00:00Z" });
    expect(seen[0].headers["X-Organization-Id"]).toBeUndefined();
    expect(seen[0].params).toEqual({
      tag: "t1",
      since: "2026-01-01T00:00:00Z",
    });
  });
});
