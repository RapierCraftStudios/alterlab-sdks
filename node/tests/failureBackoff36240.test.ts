/**
 * Coverage for #36240: the repeat-failure back-off 429 (#36158) surfaces its
 * `detail` fields and hint on `RateLimitError` and through `getErrorHint`.
 */
import { AxiosError, AxiosHeaders } from "axios";
import MockAdapter from "axios-mock-adapter";
import { AlterLab, RateLimitError, getErrorHint } from "../src/index";

const BACKOFF_HINT = {
  code: "repeat_failure_backoff",
  message:
    "This exact request returned a verification challenge 3 times in a row, " +
    "so it was paused for 60s and no credits were charged.",
};

const BACKOFF_429 = {
  error: "repeat_failure_backoff",
  message: BACKOFF_HINT.message,
  detail: {
    scope: "url",
    limit: 3,
    account_tier: "free",
    retry_after_seconds: 60,
    consecutive_failures: 3,
    outcome_class: "challenge",
    failure_code: "CAPTCHA_REQUIRED",
    hint: BACKOFF_HINT,
  },
  docs_url: "https://alterlab.io/docs/reference/error-codes",
};

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

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function makeClient(options: { maxRetries?: number } = {}) {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    ...options,
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

async function catchError(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
  } catch (e) {
    return e;
  }
  throw new Error("expected rejection");
}

function axiosErrorWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", config, null, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  });
}

describe("repeat-failure back-off 429", () => {
  it("surfaces the back-off fields and hint on RateLimitError", async () => {
    const { client, mock, sleeps } = makeClient();
    mock
      .onGet("/api/v1/usage")
      .reply(429, BACKOFF_429, { "retry-after": "60" });

    const err = await catchError(client.getUsage());

    expect(err).toBeInstanceOf(RateLimitError);
    const e = err as RateLimitError;
    // Default maxRetryWait (60s) is exceeded by the jittered 60s wait.
    expect(mock.history.get).toHaveLength(1);
    expect(sleeps).toHaveLength(0);
    expect(e.retryAfter).toBe(60);
    expect(e.errorCode).toBe("repeat_failure_backoff");
    expect(e.scope).toBe("url");
    expect(e.consecutiveFailures).toBe(3);
    expect(e.outcomeClass).toBe("challenge");
    expect(e.failureCode).toBe("CAPTCHA_REQUIRED");
    expect(e.hint).toEqual({ ...BACKOFF_HINT, reason: "" });
    expect(getErrorHint(e)?.code).toBe("repeat_failure_backoff");
  });

  it("leaves the back-off fields null for an ordinary 429", async () => {
    const { client, mock } = makeClient({ maxRetries: 1 });
    mock.onGet("/api/v1/usage").reply(429, CANONICAL_429);

    const e = (await catchError(client.getUsage())) as RateLimitError;

    expect(e).toBeInstanceOf(RateLimitError);
    expect(e.consecutiveFailures).toBeNull();
    expect(e.outcomeClass).toBeNull();
    expect(e.failureCode).toBeNull();
    expect(e.hint).toBeNull();
    expect(getErrorHint(e)).toBeNull();
  });

  it("ignores malformed back-off values", async () => {
    const { client, mock } = makeClient({ maxRetries: 1 });
    mock.onGet("/api/v1/usage").reply(429, {
      ...BACKOFF_429,
      detail: {
        ...BACKOFF_429.detail,
        consecutive_failures: "3",
        outcome_class: 1,
        failure_code: null,
        hint: { code: "repeat_failure_backoff" },
      },
    });

    const e = (await catchError(client.getUsage())) as RateLimitError;

    expect(e.consecutiveFailures).toBeNull();
    expect(e.outcomeClass).toBeNull();
    expect(e.failureCode).toBeNull();
    expect(e.hint).toBeNull();
  });

  it("getErrorHint reads detail.hint from an unwrapped AxiosError", () => {
    const err = axiosErrorWith(429, BACKOFF_429);
    expect(getErrorHint(err)).toEqual({ ...BACKOFF_HINT, reason: "" });
  });

  it("getErrorHint still prefers error.hint on a 422 body", () => {
    const hint = {
      code: "render_js_auto",
      reason: "challenge",
      message: 'Retry with render_js: "auto".',
    };
    const err = axiosErrorWith(422, {
      detail: "Scrape failed",
      error: { code: "CAPTCHA_REQUIRED", hint },
    });
    expect(getErrorHint(err)).toEqual(hint);
  });
});
