/**
 * Coverage for #40352: `jobs` is index-aligned and `resubmitRejected` resends
 * only the rejected items.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, BatchResponse, BatchScrapeRequest } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const ITEMS: BatchScrapeRequest[] = [0, 1, 2].map((i) => ({
  url: `https://example.com/${i}`,
}));

const RESPONSE: BatchResponse = {
  batch_id: "b1",
  total_urls: 3,
  estimated_credits: 2,
  job_ids: ["a", "c"],
  jobs: [
    {
      index: 0,
      url: ITEMS[0].url,
      status: "accepted",
      job_id: "a",
      rejected: null,
    },
    {
      index: 1,
      url: ITEMS[1].url,
      status: "rejected",
      job_id: null,
      rejected: {
        scope: "global_concurrent",
        reason: "x",
        retry_after_seconds: 5,
      },
    },
    {
      index: 2,
      url: ITEMS[2].url,
      status: "accepted",
      job_id: "c",
      rejected: null,
    },
  ],
  status: "processing",
  accepted_urls: 2,
  rejected_urls: 1,
  rejected_items: [],
  byos_applied: false,
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
  const bodies: { urls: { url: string }[] }[] = [];
  mock.onPost("/api/v1/batch").reply((config) => {
    bodies.push(JSON.parse(config.data ?? "{}"));
    return [202, RESPONSE];
  });
  return { client, bodies };
}

describe("resubmitRejected (#40352)", () => {
  it("resends only the rejected items", async () => {
    const { client, bodies } = setup();
    await client.resubmitRejected(ITEMS, RESPONSE);
    expect(bodies).toHaveLength(1);
    expect(bodies[0].urls.map((u) => u.url)).toEqual([ITEMS[1].url]);
  });

  it("does nothing when nothing was rejected", async () => {
    const { client, bodies } = setup();
    const accepted = {
      jobs: RESPONSE.jobs.filter((j) => j.status === "accepted"),
    };
    expect(await client.resubmitRejected(ITEMS, accepted)).toBeNull();
    expect(bodies).toHaveLength(0);
  });
});
