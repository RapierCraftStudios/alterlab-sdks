/**
 * Coverage for #39022: `attribution` is typed on ExtractResponse and
 * CrawlStatusResponse and surfaced from the API response.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, CrawlStatusResponse, ExtractResponse } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const attribution = { text: "Data via AlterLab", url: "https://alterlab.io/r/abc" };

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

describe("attribution on extract and crawl status (#39022)", () => {
  it("extract surfaces attribution", async () => {
    const { client, mock } = makeClient();
    mock.onPost("/api/v1/extract").reply(200, {
      extract_id: "e1",
      formats: {},
      credits_used: 1,
      extraction_method: "llm",
      content_size_chars: 1,
      attribution,
    });
    const res: ExtractResponse = await client.extract({ content: "<h1>x</h1>" });
    const a: { text: string; url: string } | undefined = res.attribution;
    expect(a).toEqual(attribution);
  });

  it("getCrawl surfaces attribution", async () => {
    const { client, mock } = makeClient();
    mock.onGet(/\/api\/v1\/crawl\/c1/).reply(200, {
      crawl_id: "c1",
      status: "completed",
      total: 0,
      completed: 0,
      failed: 0,
      attribution,
    });
    const res: CrawlStatusResponse = await client.getCrawl("c1");
    const a: { text: string; url: string } | undefined = res.attribution;
    expect(a).toEqual(attribution);
  });
});
