/**
 * Coverage for #39109: Node SDK feedback() sends dry_run, same_as and new.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

async function send(
  request: Parameters<AlterLab["feedback"]>[0],
  reply: Record<string, unknown> = {},
) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  let body: Record<string, unknown> = {};
  mock.onPost("/api/v1/agent/feedback").reply((config) => {
    body = JSON.parse(config.data);
    return [
      200,
      { report_id: "a", cluster_key: "k", status: "received", ...reply },
    ];
  });
  const res = await client.feedback(request);
  return { body, res };
}

describe("feedback dry_run/same_as/new (#39109)", () => {
  const base = { category: "other", happened: "x" };

  it("sends dry_run", async () => {
    const { body } = await send({ ...base, dry_run: true });
    expect(body.dry_run).toBe(true);
  });

  it("sends same_as truncated to 64 chars", async () => {
    const { body } = await send({ ...base, same_as: "c".repeat(100) });
    expect((body.same_as as string).length).toBe(64);
  });

  it("sends new", async () => {
    const { body } = await send({ ...base, new: true });
    expect(body.new).toBe(true);
  });

  it("omits all when unset", async () => {
    const { body } = await send(base);
    expect(body).not.toHaveProperty("dry_run");
    expect(body).not.toHaveProperty("same_as");
    expect(body).not.toHaveProperty("new");
  });

  it("passes matches and vote_recorded through", async () => {
    const { res } = await send(
      { ...base, dry_run: true },
      {
        matches: [{ cluster_key: "m", status: "received" }],
        vote_recorded: true,
      },
    );
    expect(res.matches?.[0].cluster_key).toBe("m");
    expect(res.vote_recorded).toBe(true);
  });
});
