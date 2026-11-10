/** #37371: after a sync_downgraded 202 the SDK long-polls `?wait=N`. */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    maxRetries: 1,
    retryDelay: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

describe("sync downgrade long-poll (#37371)", () => {
  it("requests wait=20 after a downgrade and returns the result", async () => {
    const { client, mock } = makeClient();
    mock
      .onPost("/api/v1/scrape")
      .reply(202, { job_id: "j1", sync_downgraded: true });
    const waits: unknown[] = [];
    mock.onGet("/api/v1/jobs/j1").reply((config) => {
      waits.push(config.params?.wait);
      return [
        200,
        {
          status: "succeeded",
          result: { url: "https://e.com", status_code: 200 },
        },
      ];
    });
    const out = await client.scrape({ url: "https://e.com" });
    expect(waits).toEqual([20]);
    expect(out.status_code).toBe(200);
  });

  it("plain waitForJob sends no wait param", async () => {
    const { client, mock } = makeClient();
    const waits: unknown[] = [];
    mock.onGet("/api/v1/jobs/j1").reply((config) => {
      waits.push(config.params?.wait);
      return [200, { status: "succeeded", result: {} }];
    });
    await client.waitForJob("j1");
    expect(waits).toEqual([undefined]);
  });
});
