import axios from "axios";
import {
  AlterLab,
  type Logger,
  type ScrapeRequest,
  type ScrapeResponse,
} from "./index";

// ---------------------------------------------------------------------------
// Drop-in fetch()-compatible wrapper around AlterLab's /api/v1/scrape endpoint
// ---------------------------------------------------------------------------

/**
 * Methods accepted by the underlying `/api/v1/scrape` endpoint.
 *
 * The Node SDK's `ScrapeRequest.method` type declares a broader union
 * (`"GET" | "POST" | "PUT" | "PATCH" | "DELETE"`), but the live API schema
 * (`UnifiedScrapeRequest.method` in `services/api/app/schemas/scrape.py`)
 * only accepts `Literal["GET", "POST"]` — PUT/PATCH/DELETE return HTTP 422.
 * This wrapper validates against the API's actual accepted set, not the
 * SDK's broader declared type, so unsupported methods fail fast with a
 * clear client-side error instead of a confusing 422 from the API.
 *
 * Real `fetch()` also accepts HEAD and OPTIONS, but the backend has no
 * equivalent for either — there is no way to fetch headers only or probe
 * allowed methods via `/api/v1/scrape` — so this wrapper is not a fully
 * drop-in replacement for those two methods either. HEAD/OPTIONS calls
 * fail fast with the same client-side error as PUT/PATCH/DELETE.
 */
const SUPPORTED_METHODS = new Set(["GET", "POST"]);

/** `content_type` values accepted by `ScrapeRequest.content_type`. */
const SUPPORTED_CONTENT_TYPES = new Set([
  "application/json",
  "application/x-www-form-urlencoded",
  "text/plain",
  "application/graphql",
]);

/**
 * Default logger for {@link createFetch} when no `logger` option is supplied.
 * Mirrors `index.ts`'s own (non-exported) `defaultLogger` shape so both the
 * `AlterLab` client and this wrapper log through the same console format.
 */
const defaultFetchLogger: Logger = {
  debug: (msg, ...args) => console.debug(`[alterlab] ${msg}`, ...args),
  warn: (msg, ...args) => console.warn(`[alterlab] ${msg}`, ...args),
  error: (msg, ...args) => console.error(`[alterlab] ${msg}`, ...args),
};

/**
 * Extracts a `ScrapeRequest.content_type` value from a fetch-style headers map,
 * looking up the `Content-Type` header case-insensitively and stripping any
 * `; charset=...` parameter. Returns `undefined` when absent or unrecognized,
 * letting the API fall back to its own default (`application/json`).
 *
 * When a `Content-Type` header is present but not in {@link SUPPORTED_CONTENT_TYPES},
 * emits a debug-level log via `logger` naming the dropped value, so callers have
 * a caller-visible signal that their header was silently ignored rather than
 * mistaking it for the "no header set" case (both return `undefined`).
 */
function extractContentType(
  headers: Record<string, string> | undefined,
  logger: Logger,
): ScrapeRequest["content_type"] | undefined {
  if (!headers) return undefined;
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === "content-type") {
      const mimeType = value.split(";")[0].trim().toLowerCase();
      if (SUPPORTED_CONTENT_TYPES.has(mimeType)) {
        return mimeType as ScrapeRequest["content_type"];
      }
      logger.debug(
        `Unsupported Content-Type "${mimeType}" — dropping, AlterLab API will use its own default.`,
      );
      return undefined;
    }
  }
  return undefined;
}

/**
 * Normalizes a raw axios/Node response-headers object into a flat
 * `Record<string, string>`.
 *
 * Axios (and the underlying Node `http`/`https` client it wraps) represents
 * repeated response headers — most commonly duplicate `Set-Cookie` — as a
 * `string[]` rather than a single `string`. `ScrapeResponse.headers` (and
 * `AlterLabFetchHeaders`, which wraps it) declare and consume a flat
 * `Record<string, string>`, so array values are joined with `", "` per
 * standard HTTP multi-value-header semantics before assignment. `undefined`
 * entries are dropped rather than coerced to the literal string
 * `"undefined"`.
 *
 * `Set-Cookie` is the one exception to standard multi-value-header join
 * semantics: RFC 6265 §3 disallows comma-folding it, since a comma can
 * legitimately appear inside a cookie attribute (e.g. `Expires`). Repeated
 * `set-cookie` values are joined with `"\n"` instead — matching Node's own
 * internal convention for multi-value Set-Cookie — so a value never
 * collides with a delimiter that can appear inside the header itself.
 */
function normalizeAxiosHeaders(
  raw: Record<string, string | string[] | undefined> | undefined,
): Record<string, string> {
  const result: Record<string, string> = {};
  if (!raw) return result;
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined) continue;
    if (!Array.isArray(value)) {
      result[key] = value;
      continue;
    }
    result[key] =
      key.toLowerCase() === "set-cookie" ? value.join("\n") : value.join(", ");
  }
  return result;
}

/**
 * Options for {@link createFetch}. Mirrors the subset of {@link AlterLabOptions}
 * relevant to a fetch-compatible caller.
 */
export interface AlterLabFetchOptions {
  /** AlterLab API key. Required — a real `fetch()` has no auth parameter, so it must be supplied at factory time. */
  apiKey: string;
  /** Override the API base URL (defaults to `https://api.alterlab.io`). */
  baseUrl?: string;
  /** Max retry attempts for retriable failures (429/5xx/network). Defaults to 3. */
  maxRetries?: number;
  /** Logger for debug/warn/error output (e.g. dropped Content-Type headers). Defaults to a console-based logger; pass `silentLogger` from `./index` to disable. */
  logger?: Logger;
}

/**
 * Minimal case-insensitive `Headers`-like object.
 *
 * Not a full WHATWG `Headers` polyfill — implements the handful of methods
 * most fetch-based code actually calls: `get`, `has`, `forEach`, and
 * iteration via `entries()`.
 */
export class AlterLabFetchHeaders {
  private readonly map: Map<string, string>;

  constructor(init?: Record<string, string>) {
    this.map = new Map();
    if (init) {
      for (const [key, value] of Object.entries(init)) {
        this.map.set(key.toLowerCase(), value);
      }
    }
  }

  get(name: string): string | null {
    return this.map.get(name.toLowerCase()) ?? null;
  }

  has(name: string): boolean {
    return this.map.has(name.toLowerCase());
  }

  forEach(callback: (value: string, key: string) => void): void {
    this.map.forEach((value, key) => callback(value, key));
  }

  entries(): IterableIterator<[string, string]> {
    return this.map.entries();
  }

  [Symbol.iterator](): IterableIterator<[string, string]> {
    return this.map.entries();
  }
}

/**
 * WHATWG `Response`-compatible object returned by the fetch-compatible wrapper.
 *
 * Wraps an AlterLab {@link ScrapeResponse}, exposing `.status`, `.ok`,
 * `.statusText`, `.headers`, `.text()`, and `.json()` like a real `fetch()`
 * `Response`. Does not implement streaming (`.body`) — `ScrapeResponse`
 * content is always fully buffered.
 */
export class AlterLabFetchResponse {
  /** HTTP status code returned by the target site (relayed by the scrape). */
  readonly status: number;
  /** `true` when `status` is in the 200–299 range, matching Fetch semantics. */
  readonly ok: boolean;
  /** Best-effort status text — AlterLab's scrape response does not carry one, so this is derived from `status`. */
  readonly statusText: string;
  /** Response headers from the target site, wrapped in a `Headers`-like accessor. */
  readonly headers: AlterLabFetchHeaders;
  /** The raw AlterLab scrape response this wrapper was built from, for callers that need AlterLab-specific fields (billing, tier_used, etc). */
  readonly raw: ScrapeResponse;

  private readonly rawContent: string | Record<string, unknown>;

  constructor(scrapeResponse: ScrapeResponse) {
    this.raw = scrapeResponse;
    this.status = scrapeResponse.status_code;
    this.ok = this.status >= 200 && this.status < 300;
    this.statusText = defaultStatusText(this.status);
    this.headers = new AlterLabFetchHeaders(scrapeResponse.headers);
    this.rawContent = scrapeResponse.content;
  }

  /** Resolves with the response body as a string, matching `Response.text()`. */
  async text(): Promise<string> {
    if (typeof this.rawContent === "string") {
      return this.rawContent;
    }
    return JSON.stringify(this.rawContent);
  }

  /**
   * Resolves with the response body parsed as JSON, matching `Response.json()`.
   * Rejects (does not throw synchronously) on invalid JSON, matching Fetch semantics.
   */
  async json(): Promise<unknown> {
    if (typeof this.rawContent !== "string") {
      return this.rawContent;
    }
    try {
      return JSON.parse(this.rawContent);
    } catch (error) {
      throw new Error(
        `Failed to parse response body as JSON: ${(error as Error).message}`,
      );
    }
  }
}

function defaultStatusText(status: number): string {
  const known: Record<number, string> = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
  };
  return known[status] ?? "";
}

/**
 * Subset of the standard `RequestInit` fields the wrapper understands.
 * Named separately (not aliased to `RequestInit`) so this module has no
 * dependency on DOM/undici global types being present in the consumer's
 * TypeScript config.
 */
export interface AlterLabFetchRequestInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string | Record<string, unknown>;
}

/** A `fetch(url, options)`-signature-compatible function bound to one AlterLab API key. */
export type AlterLabFetchFunction = (
  url: string,
  init?: AlterLabFetchRequestInit,
) => Promise<AlterLabFetchResponse>;

/**
 * Creates a `fetch()`-compatible function backed by AlterLab's challenge-handling
 * `/api/v1/scrape` endpoint.
 *
 * Unlike the global `fetch`, this returns a factory-bound function because a
 * real `fetch()` call carries no authentication — the AlterLab API key must be
 * supplied once, at factory time.
 *
 * ```ts
 * import { createFetch } from "alterlab";
 *
 * const fetch = createFetch({ apiKey: "sk_live_..." });
 *
 * const response = await fetch("https://example.com", {
 *   headers: { "X-Custom-Header": "value" },
 * });
 * console.log(response.status, response.ok);
 * console.log(await response.text());
 * ```
 *
 * Pass a custom `logger` (or `silentLogger` from `./index` to disable console
 * output) to control debug/warn/error output, such as the debug log emitted
 * when a `Content-Type` header is dropped for being unrecognized:
 *
 * ```ts
 * import { createFetch, silentLogger } from "alterlab";
 *
 * const fetch = createFetch({ apiKey: "sk_live_...", logger: silentLogger });
 * ```
 */
export function createFetch(
  options: AlterLabFetchOptions,
): AlterLabFetchFunction {
  const logger = options.logger ?? defaultFetchLogger;
  const client = new AlterLab({
    apiKey: options.apiKey,
    baseUrl: options.baseUrl,
    maxRetries: options.maxRetries,
    logger,
  });

  return async function alterLabFetch(
    url: string,
    init: AlterLabFetchRequestInit = {},
  ): Promise<AlterLabFetchResponse> {
    const method = (init.method ?? "GET").toUpperCase();
    if (!SUPPORTED_METHODS.has(method)) {
      throw new Error(
        `Unsupported method "${method}" — AlterLab's fetch-compatible wrapper supports: ${Array.from(
          SUPPORTED_METHODS,
        ).join(", ")}.`,
      );
    }

    let body: string | undefined;
    if (init.body !== undefined) {
      body =
        typeof init.body === "string" ? init.body : JSON.stringify(init.body);
    }

    const request: ScrapeRequest = {
      url,
      method: method as ScrapeRequest["method"],
    };
    if (init.headers !== undefined) {
      request.headers = init.headers;
    }
    if (body !== undefined) {
      request.body = body;
      const contentType = extractContentType(init.headers, logger);
      if (contentType !== undefined) {
        request.content_type = contentType;
      }
    }

    try {
      const scrapeResponse = await client.scrape(request);
      return new AlterLabFetchResponse(scrapeResponse);
    } catch (error) {
      // Real fetch() only rejects on network-level failures — an HTTP error
      // response (including one from AlterLab's own API, as opposed to the
      // target site) resolves normally with `ok: false`. `client.scrape()`
      // throws on any non-2xx AlterLab API response (rate limit, validation
      // error, auth error, etc.); translate that into a Fetch-spec-correct
      // resolution instead of letting the rejection propagate. Genuine
      // network failures (no `error.response`) still reject, matching
      // `requestWithRetry()`'s own network-vs-HTTP-error distinction.
      // WIRE:PROVEN — manual: traced index.ts's requestWithRetry() (the sole
      // caller path for client.scrape()'s underlying HTTP call). Every thrown
      // error on that path is an AxiosError — the non-retriable branch
      // (`throw error`) rethrows the raw axios rejection, and the
      // retries-exhausted branch (`throw lastError`) rethrows the same
      // AxiosError captured from the last attempt — so `axios.isAxiosError()`
      // is guaranteed true for any HTTP-level failure reaching this catch,
      // and `error.response` is present whenever the API returned a response
      // (as opposed to a connection-level failure with no response).
      if (axios.isAxiosError(error) && error.response) {
        const data: unknown = error.response.data;
        let content: string;
        if (typeof data === "string") {
          content = data;
        } else {
          // `data` is externally-sourced (AlterLab API's own error response
          // body) and can contain values JSON.stringify cannot serialize —
          // a BigInt, or a circular structure. This whole branch exists to
          // resolve gracefully with `ok: false` instead of throwing, so a
          // stringify failure must not be allowed to propagate as an
          // uncaught synchronous throw; fall back to a fixed placeholder.
          try {
            content = JSON.stringify(data ?? {});
          } catch {
            content = "[unserializable error body]";
          }
        }
        const errorResponse: ScrapeResponse = {
          url,
          status_code: error.response.status,
          content,
          headers: normalizeAxiosHeaders(
            error.response.headers as
              Record<string, string | string[] | undefined> | undefined,
          ),
          cached: false,
          credits_used: 0,
          response_time_ms: 0,
          size_bytes: Buffer.byteLength(content, "utf8"),
        };
        return new AlterLabFetchResponse(errorResponse);
      }
      throw error;
    }
  };
}

/**
 * Convenience `fetch()`-compatible export that reads the AlterLab API key from
 * `process.env.ALTERLAB_API_KEY` on first use.
 *
 * Prefer {@link createFetch} when you can pass the API key explicitly (e.g.
 * from your own config/secrets loader). This export exists so that
 * `import { fetch } from "alterlab"` — the literal drop-in pattern — works
 * out of the box for agents that already export `ALTERLAB_API_KEY` into
 * their process environment.
 *
 * Throws a clear error (rather than making an unauthenticated request) if
 * `ALTERLAB_API_KEY` is unset.
 *
 * The underlying client is cached and rebuilt only when
 * `process.env.ALTERLAB_API_KEY` changes (or is unset) between calls — so a
 * key rotation or a multi-tenant test harness that mutates the env var
 * mid-process is picked up on the next call instead of silently reusing a
 * stale client.
 */
let cachedFetch: AlterLabFetchFunction | undefined;
let cachedApiKey: string | undefined;

export const fetch: AlterLabFetchFunction = async (url, init) => {
  const apiKey = process.env.ALTERLAB_API_KEY;
  if (!apiKey) {
    throw new Error(
      "AlterLab's drop-in fetch() requires ALTERLAB_API_KEY to be set in the environment. " +
        "Set process.env.ALTERLAB_API_KEY, or use createFetch({ apiKey }) to pass a key explicitly.",
    );
  }
  if (!cachedFetch || apiKey !== cachedApiKey) {
    cachedFetch = createFetch({ apiKey });
    cachedApiKey = apiKey;
  }
  return cachedFetch(url, init);
};
