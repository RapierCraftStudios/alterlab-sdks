/**
 * Coverage for #39232: Node SDK getCrawl() sends limit, offset, sort and status.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

async function get(
  call: (client: AlterLab) => Promise<unknown>,
): Promise<Record<string, unknown> | undefined> {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  let params: Record<string, unknown> | undefined;
  mock.onGet("/api/v1/crawl/c1").reply((config) => {
    params = config.params;
    return [200, { crawl_id: "c1", status: "completed" }];
  });
  await call(client);
  return params;
}

describe("getCrawl page params (#39232)", () => {
  it("sends no params by default", async () => {
    expect(await get((c) => c.getCrawl("c1"))).toBeUndefined();
  });

  it("keeps include_results as before", async () => {
    expect(await get((c) => c.getCrawl("c1", true))).toEqual({
      include_results: "true",
    });
  });

  it("sends limit, offset, sort and status", async () => {
    const params = await get((c) =>
      c.getCrawl("c1", true, {
        limit: 10,
        offset: 20,
        sort: "url",
        status: "failed",
      }),
    );
    expect(params).toEqual({
      include_results: "true",
      limit: 10,
      offset: 20,
      sort: "url",
      status: "failed",
    });
  });

  it("sends an explicit offset of 0 and omits unset options", async () => {
    expect(await get((c) => c.getCrawl("c1", false, { offset: 0 }))).toEqual({
      offset: 0,
    });
  });
});
