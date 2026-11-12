/**
 * #40335 (ALT-311/313): every error thrown by the client is a typed class with
 * `code`, `retryable` and `requestId`; no raw AxiosError escapes and structured
 * `detail` never renders as `[object Object]`.
 */
import axios, { AxiosError } from "axios";
import MockAdapter from "axios-mock-adapter";
import {
  AlterLab,
  AlterLabError,
  ERROR_CODES,
  ERROR_CLASSES,
  InsufficientFundsError,
  RateLimitError,
  ServerError,
  describeErrorDetail,
} from "../src/index";

async function thrown(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<any> {
  const mock = new MockAdapter(axios);
  mock.onAny().reply(status, body, headers);
  const client = new AlterLab({
    apiKey: "sk_test_x",
    maxRetries: 1,
    logger: undefined,
  } as any);
  try {
    await client.scrape({ url: "https://example.com" });
  } catch (e) {
    return e;
  } finally {
    mock.restore();
  }
  throw new Error("expected scrape to throw");
}

describe("typed errors (#40335)", () => {
  it("structured detail is rendered, never [object Object] (ALT-311)", async () => {
    const e = await thrown(
      400,
      { detail: { code: "bad_request", message: "urls[0] too long" } },
      { "x-request-id": "req-1" },
    );
    expect(e).toBeInstanceOf(AlterLabError);
    expect(e).toBeInstanceOf(AxiosError);
    expect(e.message).toContain("urls[0] too long");
    expect(e.message).not.toContain("[object Object]");
    expect(e.code).toBe("bad_request");
    expect(e.retryable).toBe(false);
    expect(e.requestId).toBe("req-1");
    expect(e.statusCode).toBe(400);
  });

  it("validation arrays are joined into text", () => {
    expect(describeErrorDetail([{ msg: "a" }, { msg: "b" }, "c"])).toBe(
      "a; b; c",
    );
    expect(describeErrorDetail({ x: 1 })).toBe('{"x":1}');
  });

  it("5xx maps to a typed retryable error with request_id from the body", async () => {
    const e = await thrown(503, { request_id: "req-9", detail: "down" });
    expect(e).toBeInstanceOf(AlterLabError);
    expect(e.retryable).toBe(true);
    expect(e.requestId).toBe("req-9");
    expect(typeof e.code).toBe("string");
  });

  it("402 and 429 keep their legacy classes and gain typed fields (ALT-313)", async () => {
    const funds = await thrown(402, {
      detail: { error: "insufficient_credits", message: "Empty" },
    });
    expect(funds).toBeInstanceOf(InsufficientFundsError);
    expect(funds.code).toBe("insufficient_credits");
    expect(funds.retryable).toBe(false);

    const rl = await thrown(
      429,
      { error: "rate_limit_exceeded", detail: { retry_after_seconds: 2 } },
      { "retry-after": "2", "x-request-id": "req-r" },
    );
    expect(rl).toBeInstanceOf(RateLimitError);
    expect(rl.retryable).toBe(true);
    expect(rl.retryAfterSeconds).toBe(2);
    expect(rl.requestId).toBe("req-r");
  });

  it("network failures are typed, not raw AxiosError", async () => {
    const mock = new MockAdapter(axios);
    mock.onAny().networkError();
    const client = new AlterLab({ apiKey: "sk_test_x", maxRetries: 1 });
    let err: any;
    try {
      await client.scrape({ url: "https://example.com" });
    } catch (e) {
      err = e;
    } finally {
      mock.restore();
    }
    expect(err).toBeInstanceOf(AlterLabError);
    expect(err.code).toBe("network_error");
    expect(err.retryable).toBe(true);
  });

  it("every documented code has a class carrying its code", () => {
    for (const code of ERROR_CODES) {
      if (code === "unauthorized" || (code as string) in legacy) continue;
      expect(ERROR_CLASSES[code]).toBeDefined();
      expect((ERROR_CLASSES[code] as any).errorCode).toBe(code);
    }
    expect(ERROR_CLASSES.server_error).toBe(ServerError);
  });
});

const legacy: Record<string, true> = {
  insufficient_credits: true,
  rate_limited: true,
  rate_limit_exceeded: true,
};
