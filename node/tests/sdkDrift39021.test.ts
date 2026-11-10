/**
 * Coverage for #39021: `extraction_selectors` is accepted by the typed scrape,
 * estimateCost, extract and batchScrape requests and reaches the POST body.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, ExtractionSelectors } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const selectors: ExtractionSelectors = {
  title: { css: "h1" },
  links: { xpath: "//a", attr: "href", multiple: true },
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

describe("extraction_selectors (#39021)", () => {
  it("scrape sends extraction_selectors", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/scrape").reply(capture);
    await client.scrape({
      url: "https://example.com",
      extraction_selectors: selectors,
    });
    expect(bodies[0].extraction_selectors).toEqual(selectors);
  });

  it("estimateCost sends extraction_selectors", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/scrape/estimate").reply(capture);
    await client.estimateCost({
      url: "https://example.com",
      extraction_selectors: selectors,
    });
    expect(bodies[0].extraction_selectors).toEqual(selectors);
  });

  it("extract sends extraction_selectors", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/extract").reply(capture);
    await client.extract({
      content: "<h1>x</h1>",
      extraction_selectors: selectors,
    });
    expect(bodies[0].extraction_selectors).toEqual(selectors);
  });

  it("batchScrape sends batch-level and per-item extraction_selectors", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/batch").reply(capture);
    await client.batchScrape({
      urls: [{ url: "https://example.com", extraction_selectors: selectors }],
      extraction_selectors: { t: { css: "title" } },
    });
    expect(bodies[0].extraction_selectors).toEqual({ t: { css: "title" } });
    expect(
      (bodies[0].urls as Record<string, unknown>[])[0].extraction_selectors,
    ).toEqual(selectors);
  });
});
