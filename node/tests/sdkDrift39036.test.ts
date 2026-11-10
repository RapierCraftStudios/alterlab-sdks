/**
 * Coverage for #39036: billing.estimated_credits and the estimate range
 * fields are typed on the Node SDK responses.
 */
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  BillingDetails,
  CostEstimateResponse,
  EstimateDriver,
} from "../src/index";

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

describe("estimate range and billing.estimated_credits (#39036)", () => {
  it("estimateCost surfaces range fields and drivers", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/scrape/estimate").reply(200, {
      url: "https://example.com",
      estimated_tier: "1",
      estimated_credits: 10,
      confidence: "high",
      max_possible_credits: 40,
      reasoning: "r",
      min_credits: 5,
      likely_credits: 10,
      max_credits: 40,
      drivers: [{ name: "egress", detail: "d" }],
    });
    const res: CostEstimateResponse = await client.estimateCost({
      url: "https://example.com",
    });
    const min: number | null | undefined = res.min_credits;
    const drivers: EstimateDriver[] | undefined = res.drivers;
    expect(min).toBe(5);
    expect(res.likely_credits).toBe(10);
    expect(res.max_credits).toBe(40);
    expect(drivers?.[0].name).toBe("egress");
  });

  it("BillingDetails types estimated_credits", () => {
    const b: Pick<BillingDetails, "estimated_credits"> = {
      estimated_credits: 12,
    };
    expect(b.estimated_credits).toBe(12);
  });
});
