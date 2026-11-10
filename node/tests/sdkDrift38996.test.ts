/**
 * Coverage for #38996: `response` ("full" | "minimal") is accepted by the typed
 * scrape and estimateCost requests and reaches the POST body.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: Record<string, unknown>[] = [];
  const capture = (config: { data?: string }): [number, unknown] => {
    bodies.push(JSON.parse(config.data ?? "{}"));
    return [200, {}];
  };
  return { client, mock, bodies, capture };
}

describe("response shape (#38996)", () => {
  it("scrape sends `response`", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/scrape").reply(capture);
    await client.scrape({ url: "https://example.com", response: "minimal" });
    expect(bodies[0].response).toBe("minimal");
  });

  it("estimateCost sends `response`", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/scrape/estimate").reply(capture);
    await client.estimateCost({ url: "https://example.com", response: "full" });
    expect(bodies[0].response).toBe("full");
  });
});
