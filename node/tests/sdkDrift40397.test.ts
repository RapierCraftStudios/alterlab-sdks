/**
 * Coverage for #40397: Node SDK response types expose `BatchResponse.docs_url`
 * and `ScrapeResponse.hints` from the OpenAPI spec.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";
import type { BatchResponse, ScrapeResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("response drift (#40397)", () => {
  it("batchScrape passes docs_url through", async () => {
    const client = new AlterLab({
      apiKey: "sk_test",
      logger: silentLogger,
    } as never);
    const mock = new MockAdapter((client as any).client);
    mock.onPost(/\/api\/v1\/batch$/).reply(200, {
      batch_id: "b1",
      total_urls: 1,
      status: "partial",
      docs_url: "https://alterlab.io/docs/batch",
    });
    const res: BatchResponse = await client.batchScrape([
      { url: "https://example.com" },
    ]);
    expect(res.docs_url).toBe("https://alterlab.io/docs/batch");
  });

  it("types accept docs_url and hints", () => {
    const b: Partial<BatchResponse> = { docs_url: null };
    const s: Partial<ScrapeResponse> = {
      hints: [{ format: "json_v2", why: "structured" }],
    };
    expect(b.docs_url).toBeNull();
    expect(s.hints).toHaveLength(1);
  });
});
