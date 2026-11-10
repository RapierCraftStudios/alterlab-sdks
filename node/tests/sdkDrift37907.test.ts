/**
 * Coverage for #37907: Node SDK exposes the `agent_profile`, `max_tokens` and
 * `PAYMENT-SIGNATURE` scrape params, the estimate-endpoint `agent_profile`,
 * `max_age` and `max_tokens`, and names the job-status long-poll param `wait`.
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
  return { client, mock };
}

describe("scrape agent profile and payment signature (#37907)", () => {
  it("sends agent_profile/max_tokens in the body and the signature as a header", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(200, {
      url: "https://example.com",
      status_code: 200,
      content: "x",
    });
    await client.scrape({
      url: "https://example.com",
      agent_profile: "agent",
      max_tokens: 500,
      paymentSignature: "base64payload",
    });
    const req = mock.history.post[0];
    const body = JSON.parse(req.data);
    expect(body.agent_profile).toBe("agent");
    expect(body.max_tokens).toBe(500);
    expect(body).not.toHaveProperty("paymentSignature");
    expect(body).not.toHaveProperty("payment_signature");
    expect(req.headers?.["PAYMENT-SIGNATURE"]).toBe("base64payload");
  });

  it("omits the header when no signature is given", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape").reply(200, { url: "u", status_code: 200 });
    await client.scrape({ url: "https://example.com" });
    expect(mock.history.post[0].headers?.["PAYMENT-SIGNATURE"]).toBeUndefined();
  });
});

describe("estimateCost new params (#37907)", () => {
  it("passes agent_profile, max_age and max_tokens", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape/estimate").reply(200, {});
    await client.estimateCost({
      url: "https://example.com",
      agent_profile: "agent",
      max_age: 60,
      max_tokens: 1000,
    });
    expect(JSON.parse(mock.history.post[0].data)).toMatchObject({
      agent_profile: "agent",
      max_age: 60,
      max_tokens: 1000,
    });
  });
});

describe("getJobStatus wait (#37907)", () => {
  it("sends wait as the query param", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/jobs/j1").reply(200, { status: "succeeded" });
    await client.getJobStatus("j1", 5);
    expect(mock.history.get[0].params).toEqual({ wait: 5 });
  });
});
