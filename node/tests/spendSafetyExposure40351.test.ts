/** #40351: approval exposure in the Node SDK. */
import { AlterLab } from "../src/index";

function makeClient() {
  const client = new AlterLab({ apiKey: "sk_test_dummy" });
  const calls: Array<{ method?: string; url?: string; data?: any }> = [];
  (client as any).requestWithRetry = async (config: any) => {
    calls.push(config);
    return { status: "approved" };
  };
  return { client, calls };
}

describe("spend approval exposure (#40351)", () => {
  it("crawl maps approvalId to approval_id", async () => {
    const { client, calls } = makeClient();
    await client.crawl({ url: "https://example.com", approvalId: "apr_1" });
    expect(calls[0].data.approval_id).toBe("apr_1");
  });

  it("batchScrape passes approval_id through", async () => {
    const { client, calls } = makeClient();
    await client.batchScrape({
      urls: [{ url: "https://example.com/a" }],
      approval_id: "apr_2",
    });
    expect(calls[0].data.approval_id).toBe("apr_2");
  });

  it("approval and tag threshold routes", async () => {
    const { client, calls } = makeClient();
    await client.getApproval("apr 1");
    await client.getTagApproval("nightly");
    await client.setTagApproval("nightly", 5);
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["GET", "/api/v1/approvals/apr%201"],
      ["GET", "/api/v1/usage-tags/nightly/approval"],
      ["PUT", "/api/v1/usage-tags/nightly/approval"],
    ]);
    expect(calls[2].data).toEqual({ approval_above_usd: 5 });
  });
});
