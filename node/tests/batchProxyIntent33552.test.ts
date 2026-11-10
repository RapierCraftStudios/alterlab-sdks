/**
 * Coverage for #33552: Node batch items carry omission-safe proxy intent.
 * Unset `use_proxy` must stay off the wire (platform-driven reactive routing);
 * explicit false/true are sent verbatim as API `advanced.use_proxy`.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchScrapeRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const BATCH_RESPONSE = {
  batch_id: "b1",
  total_urls: 1,
  estimated_credits: 1,
  job_ids: ["j1"],
  status: "queued",
  accepted_urls: 1,
  rejected_urls: 0,
  rejected_items: [],
  byos_applied: false,
};

async function sendItem(
  item: BatchScrapeRequest,
): Promise<Record<string, unknown>> {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: { urls: Record<string, unknown>[] }[] = [];
  mock.onPost("/api/v1/batch").reply((config) => {
    bodies.push(JSON.parse(config.data ?? "{}"));
    return [200, BATCH_RESPONSE];
  });
  await client.batchScrape([item]);
  return bodies[0].urls[0];
}

const URL = "https://example.com/a";

describe("batchScrape proxy intent (#33552)", () => {
  it("omits use_proxy when the caller leaves it unset", async () => {
    expect(await sendItem({ url: URL })).toEqual({ url: URL });
    expect(await sendItem({ url: URL, advanced: { render_js: true } })).toEqual(
      { url: URL, advanced: { render_js: true } },
    );
    expect(
      await sendItem({ url: URL, advanced: { useProxy: undefined } }),
    ).toEqual({ url: URL, advanced: {} });
  });

  it.each([false, true])(
    "sends advanced.useProxy=%s as use_proxy",
    async (value) => {
      expect(
        await sendItem({ url: URL, advanced: { useProxy: value } }),
      ).toEqual({ url: URL, advanced: { use_proxy: value } });
    },
  );

  it.each([false, true])(
    "sends advanced.use_proxy=%s verbatim",
    async (value) => {
      expect(
        await sendItem({ url: URL, advanced: { use_proxy: value } }),
      ).toEqual({ url: URL, advanced: { use_proxy: value } });
    },
  );

  it.each([false, true])(
    "moves the use_proxy=%s shorthand into advanced",
    async (value) => {
      expect(await sendItem({ url: URL, use_proxy: value })).toEqual({
        url: URL,
        advanced: { use_proxy: value },
      });
    },
  );

  it("lets values set in advanced override the shorthand", async () => {
    expect(
      await sendItem({
        url: URL,
        use_proxy: true,
        advanced: { useProxy: false },
      }),
    ).toEqual({ url: URL, advanced: { use_proxy: false } });
    expect(
      await sendItem({
        url: URL,
        advanced: { use_proxy: true, useProxy: false },
      }),
    ).toEqual({ url: URL, advanced: { use_proxy: true } });
  });
});
