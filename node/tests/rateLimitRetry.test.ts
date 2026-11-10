/**
 * Coverage for #34582: 429 handling honours Retry-After with jitter, stops at
 * `maxRetryWait` instead of blocking for minutes, and surfaces the canonical
 * 429 body fields (#34574) on `RateLimitError`.
 */
import axios from "axios";
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  RateLimitError,
  computeRetrySleepMs,
  parseRetryAfterMs,
} from "../src/index";

const CANONICAL_429 = {
  error: "rate_limit_exceeded",
  message: "Rate limit for your plan (Free): 30 requests/minute. Retry in 2s.",
  detail: {
    scope: "account",
    limit: 30,
    account_tier: "free",
    retry_after_seconds: 2,
  },
  docs_url: "https://alterlab.io/docs/reference/limits",
};

const CANONICAL_HEADERS = {
  "retry-after": "2",
  "ratelimit-limit": "30",
  "ratelimit-remaining": "0",
  "ratelimit-reset": "2",
  "x-ratelimit-scope": "account",
};

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function makeClient(options: {
  maxRetries?: number;
  retryDelay?: number;
  maxRetryWait?: number | null;
}) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    ...options,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  // Record requested sleeps instead of sleeping.
  const sleeps: number[] = [];
  (client as unknown as { sleep: (ms: number) => Promise<void> }).sleep = (
    ms: number,
  ) => {
    sleeps.push(ms);
    return Promise.resolve();
  };
  return { client, mock, sleeps };
}

async function catchError(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
  } catch (e) {
    return e;
  }
  throw new Error("expected rejection");
}

describe("429 retry handling", () => {
  it("surfaces canonical 429 fields and waits at least Retry-After", async () => {
    const { client, mock, sleeps } = makeClient({
      maxRetries: 3,
      retryDelay: 10,
    });
    mock.onGet("/api/v1/usage").reply(429, CANONICAL_429, CANONICAL_HEADERS);

    const err = await catchError(client.getUsage());

    expect(err).toBeInstanceOf(RateLimitError);
    const e = err as RateLimitError;
    expect(axios.isAxiosError(e)).toBe(true);
    expect(e.response?.status).toBe(429);
    expect(e.message).toBe(CANONICAL_429.message);
    expect(e.retryAfter).toBe(2);
    expect(e.errorCode).toBe("rate_limit_exceeded");
    expect(e.scope).toBe("account");
    expect(e.limit).toBe(30);
    expect(e.accountTier).toBe("free");
    expect(e.docsUrl).toBe("https://alterlab.io/docs/reference/limits");
    expect(e.rateLimitLimit).toBe("30");
    expect(e.rateLimitRemaining).toBe("0");
    expect(e.rateLimitReset).toBe("2");

    // 3 attempts -> 2 sleeps, each the 2s floor plus at most 20% jitter.
    expect(sleeps).toHaveLength(2);
    for (const ms of sleeps) {
      expect(ms).toBeGreaterThanOrEqual(2000);
      expect(ms).toBeLessThanOrEqual(2400);
    }
  });

  it("raises RateLimitError for an edge 429 with no JSON and no Retry-After", async () => {
    const { client, mock, sleeps } = makeClient({
      maxRetries: 2,
      retryDelay: 1000,
    });
    mock.onGet("/api/v1/usage").reply(429, "error code: 1015");

    const e = (await catchError(client.getUsage())) as RateLimitError;

    expect(e).toBeInstanceOf(RateLimitError);
    expect(e.response?.data).toBe("error code: 1015");
    expect(e.retryAfter).toBeNull();
    expect(e.errorCode).toBeNull();
    expect(e.scope).toBeNull();
    expect(e.limit).toBeNull();
    // Jittered exponential backoff without a server hint: [500, 1000] ms.
    expect(sleeps).toHaveLength(1);
    expect(sleeps[0]).toBeGreaterThanOrEqual(500);
    expect(sleeps[0]).toBeLessThanOrEqual(1000);
  });

  it("parses an HTTP-date Retry-After instead of sleeping NaN", async () => {
    const { client, mock } = makeClient({ maxRetries: 1 });
    const retryAt = new Date(Date.now() + 30_000).toUTCString();
    mock
      .onGet("/api/v1/usage")
      .reply(429, "error code: 1015", { "retry-after": retryAt });

    const e = (await catchError(client.getUsage())) as RateLimitError;
    expect(e.retryAfter).toBeGreaterThanOrEqual(25);
    expect(e.retryAfter).toBeLessThanOrEqual(30);
  });

  it("throws immediately when Retry-After exceeds maxRetryWait", async () => {
    const { client, mock, sleeps } = makeClient({
      maxRetries: 5,
      maxRetryWait: 30_000,
    });
    mock
      .onGet("/api/v1/usage")
      .reply(429, CANONICAL_429, {
        ...CANONICAL_HEADERS,
        "retry-after": "600",
      });

    const e = (await catchError(client.getUsage())) as RateLimitError;

    expect(e).toBeInstanceOf(RateLimitError);
    expect(e.retryAfter).toBe(600);
    expect(sleeps).toEqual([]);
    expect(mock.history.get).toHaveLength(1);
  });

  it("caps the total sleep across attempts at maxRetryWait", async () => {
    const { client, mock, sleeps } = makeClient({
      maxRetries: 10,
      retryDelay: 10,
      maxRetryWait: 5000,
    });
    mock.onGet("/api/v1/usage").reply(429, CANONICAL_429, CANONICAL_HEADERS);

    await expect(client.getUsage()).rejects.toBeInstanceOf(RateLimitError);
    expect(sleeps).toHaveLength(2);
    expect(sleeps.reduce((a, b) => a + b, 0)).toBeLessThanOrEqual(5000);
    expect(mock.history.get).toHaveLength(3);
  });

  it("returns the response after a 429 followed by success", async () => {
    const { client, mock, sleeps } = makeClient({ retryDelay: 10 });
    mock
      .onGet("/api/v1/usage")
      .replyOnce(429, CANONICAL_429, CANONICAL_HEADERS)
      .onGet("/api/v1/usage")
      .replyOnce(200, { credits: 1 });

    await expect(client.getUsage()).resolves.toEqual({ credits: 1 });
    expect(sleeps).toHaveLength(1);
  });

  it("rejects a negative maxRetryWait", () => {
    expect(() => makeClient({ maxRetryWait: -1 })).toThrow(/maxRetryWait/);
  });
});

describe("retry helpers", () => {
  it("parses Retry-After forms", () => {
    expect(parseRetryAfterMs(undefined)).toBeNull();
    expect(parseRetryAfterMs("")).toBeNull();
    expect(parseRetryAfterMs("garbage")).toBeNull();
    expect(parseRetryAfterMs("7")).toBe(7000);
    expect(parseRetryAfterMs("-3")).toBe(0);
    expect(
      parseRetryAfterMs(new Date(Date.now() - 3_600_000).toUTCString()),
    ).toBe(0);
  });

  it("jitters the backoff", () => {
    const plain = new Set(
      Array.from({ length: 50 }, () => computeRetrySleepMs(3, 1000, null)),
    );
    expect(plain.size).toBeGreaterThan(1);
    for (const ms of plain) {
      expect(ms).toBeGreaterThanOrEqual(4000);
      expect(ms).toBeLessThanOrEqual(8000);
    }
    const hinted = new Set(
      Array.from({ length: 50 }, () => computeRetrySleepMs(0, 1000, 10_000)),
    );
    expect(hinted.size).toBeGreaterThan(1);
    for (const ms of hinted) {
      expect(ms).toBeGreaterThanOrEqual(10_000);
      expect(ms).toBeLessThanOrEqual(12_000);
    }
  });
});
