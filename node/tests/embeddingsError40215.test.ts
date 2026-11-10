/** #40215: `embeddings_error` is typed on ScrapeResponse and passes through. */
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  type EmbeddingsError,
  type ScrapeResponse,
} from "../src/index";

describe("embeddings_error (#40215)", () => {
  it("returns typed code/message", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      maxRetries: 1,
      retryDelay: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    mock.onPost("/api/v1/scrape").reply(200, {
      url: "https://example.com",
      status_code: 200,
      content: { markdown: "ok" },
      embeddings_error: { code: "quota", message: "Provider quota exceeded." },
    });
    const res: ScrapeResponse = await client.scrape({
      url: "https://example.com",
      embeddings: { enabled: true },
    });
    const err: EmbeddingsError | null | undefined = res.embeddings_error;
    expect(err?.code).toBe("quota");
    expect(err?.message).toBe("Provider quota exceeded.");
  });
});
