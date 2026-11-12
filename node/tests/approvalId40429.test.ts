/**
 * Coverage for #40429: `approval_id` on batchScrape and `approvalId` on crawl
 * are typed and sent on the wire only when set.
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
  const bodies: Record<string, unknown>[] = [];
  const reply = (config: { data?: string }) => {
    bodies.push(JSON.parse(config.data as string));
    return [200, {}];
  };
  mock.onPost("/api/v1/batch").reply(reply);
  mock.onPost("/api/v1/crawl").reply(reply);
  return { client, bodies };
}

describe("approval_id (#40429)", () => {
  it("batchScrape forwards approval_id", async () => {
    const { client, bodies } = setup();
    await client.batchScrape({
      urls: [{ url: "https://example.com/a" }],
      approval_id: "apr_123",
    });
    expect(bodies[0].approval_id).toBe("apr_123");
  });

  it("crawl maps approvalId to approval_id", async () => {
    const { client, bodies } = setup();
    await client.crawl({ url: "https://example.com", approvalId: "apr_123" });
    expect(bodies[0].approval_id).toBe("apr_123");
  });

  it("omits approval_id by default", async () => {
    const { client, bodies } = setup();
    await client.batchScrape({ urls: [{ url: "https://example.com/a" }] });
    await client.crawl({ url: "https://example.com" });
    expect(bodies[0]).not.toHaveProperty("approval_id");
    expect(bodies[1]).not.toHaveProperty("approval_id");
  });
});
