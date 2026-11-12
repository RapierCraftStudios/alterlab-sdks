/**
 * #40324: a spend_limit_exceeded 429 is terminal. The SDK throws immediately
 * and never sleeps, while transient 429s keep retrying.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab, RateLimitError } from "../src/index";

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
    maxRetries: 3,
    retryDelay: 10,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const sleeps: number[] = [];
  (client as unknown as { sleep: (ms: number) => Promise<void> }).sleep = (
    ms: number,
  ) => {
    sleeps.push(ms);
    return Promise.resolve();
  };
  return { client, mock, sleeps };
}

const SPEND_429 = {
  error: "spend_limit_exceeded",
  message: "API key budget limit reached.",
  detail: {
    scope: "key_budget",
    limit: 5000000,
    retry_after_seconds: 60,
    retryable: false,
    retry_at: "2026-11-11T07:00:00+00:00",
    period: "daily",
  },
  docs_url: "https://alterlab.io/docs/reference/limits",
};

async function catchError(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
  } catch (e) {
    return e;
  }
  throw new Error("expected rejection");
}

describe("spend_limit_exceeded is terminal (#40324)", () => {
  it("does not sleep or retry, even with a short Retry-After", async () => {
    const { client, mock, sleeps } = makeClient();
    mock.onGet("/api/v1/usage").reply(429, SPEND_429, { "retry-after": "1" });

    const err = await catchError(client.getUsage());

    expect(err).toBeInstanceOf(RateLimitError);
    const e = err as RateLimitError;
    expect(e.terminal).toBe(true);
    expect(e.retryable).toBe(false);
    expect(e.retryAt).toBe("2026-11-11T07:00:00+00:00");
    expect(sleeps).toEqual([]);
    expect(mock.history.get.length).toBe(1);
  });

  it("treats retryable=false on any error code as terminal", async () => {
    const { client, mock, sleeps } = makeClient();
    const body = { ...SPEND_429, error: "something_else" };
    mock.onGet("/api/v1/usage").reply(429, body, { "retry-after": "1" });

    const err = (await catchError(client.getUsage())) as RateLimitError;

    expect(err.terminal).toBe(true);
    expect(sleeps).toEqual([]);
    expect(mock.history.get.length).toBe(1);
  });

  it("still retries a transient 429", async () => {
    const { client, mock, sleeps } = makeClient();
    mock.onGet("/api/v1/usage").reply(
      429,
      {
        error: "rate_limit_exceeded",
        message: "slow down",
        detail: { scope: "account", retry_after_seconds: 1 },
      },
      { "retry-after": "1" },
    );

    const err = (await catchError(client.getUsage())) as RateLimitError;

    expect(err.terminal).toBe(false);
    expect(sleeps.length).toBe(2);
    expect(mock.history.get.length).toBe(3);
  });
});
