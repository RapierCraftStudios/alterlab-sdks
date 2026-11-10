/**
 * Coverage for #37227: SearchStatusResponse exposes ad and cost_breakdown fields.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, SearchAdResult, SearchStatusResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("getSearch status ad fields (#37227)", () => {
  it("returns typed ad_results, ads_* and cost_breakdown", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const ad: SearchAdResult = { position: 1, slot: "top", title: "Ad" };
    mock.onGet("/api/v1/search/s1").reply(200, {
      search_id: "s1",
      query: "q",
      status: "completed",
      results_requested: 1,
      results_count: 0,
      completed: 0,
      cost_breakdown: { base: 1 },
      ad_results: [ad],
      ads_top: [ad],
      ads_bottom: [],
      ads_shopping: [],
    });
    const res: SearchStatusResponse = await client.getSearch("s1");
    const top: SearchAdResult[] | undefined = res.ads_top;
    const cost: Record<string, unknown> | null | undefined = res.cost_breakdown;
    expect(top?.[0].slot).toBe("top");
    expect(res.ad_results).toHaveLength(1);
    expect(res.ads_bottom).toEqual([]);
    expect(res.ads_shopping).toEqual([]);
    expect(cost).toEqual({ base: 1 });
  });
});
