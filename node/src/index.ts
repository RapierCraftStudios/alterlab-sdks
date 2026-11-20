import axios, {
  AxiosInstance,
  AxiosError,
  AxiosRequestConfig,
  AxiosResponse,
} from "axios";
import { assertDownloadActionLimit } from "./actions";
import type {
  ActionObservation,
  ArtifactDelivery,
  ArtifactMetadata,
  ScrapeAction,
} from "./actions";
import * as artifactHelpers from "./artifacts";
import { createParity } from "./mcpNamespaces";
import type {
  McpParity,
  AccountNamespace,
  SupportNamespace,
  JobsNamespace,
  MonitorsNamespace,
  SchedulesNamespace,
  StoreNamespace,
  FeedsNamespace,
  WorkflowsNamespace,
  ScrapeIssueType,
  ReportScrapeOptions,
  SupportTicketRequest,
  UnexpectedResponseHook,
} from "./mcpNamespaces";
import type { ArtifactUrl } from "./artifacts";
import { detailHintSource, parseFailureBackoffDetail } from "./failure-backoff";

export type { FailureBackoffOutcomeClass } from "./failure-backoff";
import {
  applyTypedFields,
  toTypedError,
  type BatchStatusResponse,
} from "./transport.generated";
export * as transport from "./transport.generated";
export {
  AlterLabError,
  ERROR_CODES,
  ERROR_CLASSES,
  describeErrorDetail,
  toTypedError,
  type ErrorCode,
  type TypedErrorFields,
} from "./transport.generated";
export {
  BadGatewayError,
  BadRequestError,
  BlockedUpstreamError,
  ClientError,
  ConflictError,
  CrawlConcurrencyLimitReachedError,
  ForbiddenError,
  GatewayTimeoutError,
  InternalError,
  InvalidInputError,
  InvalidVersionError,
  ListingDegradedError,
  ListingNotFoundError,
  ListingRunNotFoundError,
  ListingRunUnavailableError,
  MethodNotAllowedError,
  NetworkError,
  NotFoundError,
  PayloadTooLargeError,
  RepeatFailureBackoffError,
  RequestCancelledError,
  RequestTimeoutError,
  ServerError,
  ServiceUnavailableError,
  SessionRequiredError,
  SpendCapExceededError,
  SpendLimitExceededError,
  UnauthorizedError,
  ValidationError,
} from "./transport.generated";
export * from "./research";
import {
  RESEARCH_SETTLED_STATUSES,
  parseSseEvents,
  type ResearchEvent,
  type ResearchJob,
  type ResearchRequest,
  type WaitForResearchOptions,
} from "./research";

/** Response from `POST /v1/batch/{batch_id}/resume`. */
export interface BatchResumeResponse {
  batch_id: string;
  /** Items re-enqueued after the `paused_low_success` stop. */
  resumed: number;
  status: string;
}

/** Next step an agent shows its human when work is held for approval. */
export interface PendingApprovalNextAction {
  type: string;
  approval_url: string;
  poll_after_seconds?: number;
  [key: string]: unknown;
}

/**
 * Accepted-but-held response (HTTP 202) of a batch or crawl estimated above the
 * key's or tag's `approval_above_usd`. Nothing was dispatched or charged. Show
 * `next_action.approval_url` to the account owner, poll `getApproval()` until
 * `approved`, then resubmit the identical request with `approval_id`.
 * `batchScrape()`/`crawl()` keep their declared return types, so cast the result.
 */
export interface PendingApproval {
  status: "pending_approval";
  approval_id?: string;
  approval_url?: string;
  next_action: PendingApprovalNextAction;
  [key: string]: unknown;
}

/** Response of `GET /v1/approvals/{approval_id}` and the tag threshold endpoints. */
export interface ApprovalStatus {
  approval_id: string;
  status: "pending" | "approved" | "denied" | "consumed";
  estimated_microcents?: number;
  estimated_usd?: number;
  approval_above_usd?: number | null;
  approval_url: string;
  expires_at?: string | null;
}

/** A request tag's approval threshold (`null` means no threshold). */
/** Body for the spend-limit endpoints (`SpendLimitConfig`). */
export interface SpendLimitConfig {
  enabled?: boolean;
  request_limit?: number | null;
  budget_limit_microcents?: number | null;
  reset_period?: "daily" | "weekly" | "monthly";
  approval_above_usd?: number | null;
}

export interface TagApproval {
  tag: string;
  approval_above_usd: number | null;
}

/** SDK version — keep in sync with package.json */
const SDK_VERSION = "2.5.6";

/** Status codes that should trigger a retry */
const RETRIABLE_STATUS_CODES = new Set([429, 500, 502, 503, 504]);

/**
 * Default ceiling (ms) on the total time one request may spend sleeping
 * between retries. A Retry-After that would push past it is not waited out:
 * the error (carrying `retryAfter`) is thrown immediately so the caller
 * decides when to come back instead of the call blocking for minutes.
 */
const DEFAULT_MAX_RETRY_WAIT_MS = 60_000;

/**
 * A server-supplied Retry-After is a floor; up to this fraction is added on
 * top so clients that were rejected together do not retry in lockstep.
 */
const RETRY_AFTER_JITTER = 0.2;

/**
 * Parse a `Retry-After` header (delta-seconds or HTTP-date, RFC 9110) into
 * non-negative milliseconds, or `null` when absent or unparseable (an
 * edge/WAF 429 can carry anything).
 */
export function parseRetryAfterMs(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const text = String(value).trim();
  if (!text) return null;
  let ms: number;
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    ms = Number(text) * 1000;
  } else {
    const when = Date.parse(text);
    if (Number.isNaN(when)) return null;
    ms = when - Date.now();
  }
  if (!Number.isFinite(ms)) return null;
  return Math.max(0, ms);
}

/**
 * Jittered exponential backoff, never shorter than `retryAfterMs`.
 *
 * Without a server hint the delay is "equal jitter" over
 * `retryDelay * 2 ** attempt`; with one, the server value plus up to
 * {@link RETRY_AFTER_JITTER} of itself, or the backoff if that is longer.
 */
export function computeRetrySleepMs(
  attempt: number,
  retryDelay: number,
  retryAfterMs: number | null,
): number {
  const base = retryDelay * Math.pow(2, attempt);
  const backoff = base * (0.5 + Math.random() * 0.5);
  if (retryAfterMs === null) return backoff;
  return Math.max(
    retryAfterMs * (1 + Math.random() * RETRY_AFTER_JITTER),
    backoff,
  );
}

/**
 * Return `value` guaranteed to be a valid US-ASCII HTTP header value.
 *
 * HTTP header field values must be US-ASCII (RFC 7230); Node's `http`
 * module (and axios's default adapter, which delegates to it) throws
 * `TypeError: Invalid character in header content` if handed a non-ASCII
 * string directly, crashing the request before it is ever sent (#28634).
 * Printable ASCII strings -- the overwhelmingly common case -- pass through
 * byte-identical to preserve existing behavior; anything else is
 * percent-encoded.
 *
 * "Anything else" deliberately includes ASCII control characters such as
 * CR/LF: a raw newline in a header value also crashes the transport (and
 * would smuggle a header break if it did not), so it must be encoded too.
 * Unpaired UTF-16 surrogates are replaced with U+FFFD first so
 * `encodeURIComponent` cannot throw `URIError` -- the very error class this
 * helper exists to prevent -- and `!*'()` are additionally escaped so the
 * output matches the Python SDK's `_ascii_safe_header_value`
 * (`quote(safe="")`, RFC 3986) byte-for-byte across both SDKs.
 */
function asciiSafeHeaderValue(value: string): string {
  // Fast path: printable ASCII (0x20-0x7E, includes space) is already a valid
  // header value. Control chars (CR, LF, tab, DEL) fall through to the encoder.
  if (/^[\x20-\x7E]*$/.test(value)) {
    return value;
  }
  let encoded: string;
  try {
    encoded = encodeURIComponent(value);
  } catch {
    // Unpaired UTF-16 surrogates make encodeURIComponent throw URIError.
    // Replace only lone surrogates (valid astral pairs are preserved), then
    // re-encode.
    encoded = encodeURIComponent(
      value.replace(
        /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g,
        "�",
      ),
    );
  }
  return encoded.replace(
    /[!*'()]/g,
    (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase(),
  );
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Details of a single tier escalation attempt within a scrape request.
 *
 * These fields are marked `x-internal` and may not appear in all API responses
 * (they are filtered from the public OpenAPI spec). Present when the account
 * has access to internal billing diagnostics.
 */
export interface TierEscalationDetail {
  /** Tier identifier that was attempted (e.g. `"1"`, `"2"`, `"3"`, `"3.5"`, `"4"`). */
  tier: string;
  /** Outcome of this tier attempt. */
  result: "success" | "failed" | "skipped";
  /** Credits charged for this tier attempt (microcents). Internal. */
  credits: number;
  /** Time taken for this tier attempt in milliseconds. Internal. */
  duration_ms?: number | null;
  /** Error message if the tier attempt failed. Internal. */
  error?: string | null;
}

/**
 * Detailed billing breakdown returned in every scrape response.
 *
 * Accessed via `response.billing`. All cost values are in microcents
 * (divide by 1 000 000 to get USD).
 */
export interface BillingDetails {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  /** Total credits charged for the request (microcents). */
  total_credits: number;
  /** Scraping tier that produced the final result (e.g. `"1"`, `"4"`). */
  tier_used: string;
  /**
   * Ordered list of tier attempts made for this request. Internal — only
   * present when `x-internal` fields are not filtered by the server.
   */
  escalations?: TierEscalationDetail[];
  /** Credits saved vs. always using the highest tier. Internal. */
  savings?: number;
  /** Advisory on how to reduce cost next time. Internal. */
  optimization_suggestion?: string | null;
  /** Pre-flight likely cost for this request (see `estimateCost`), to compare with `total_credits`. */
  estimated_credits?: number | null;
  /** Whether a Bring-Your-Own-Proxy discount was applied. */
  byop_applied: boolean;
  /** Discount percentage applied when BYOP is active (e.g. `98.4` for 98.4% off). */
  byop_discount_percent?: number | null;
  /** Original cost before BYOP discount in microcents. */
  original_cost_microcents?: number | null;
  /** Final cost after BYOP discount in microcents. */
  final_cost_microcents?: number | null;
  /** Whether Bring-Your-Own-Session cookies were injected into this request. */
  byos_applied: boolean;
  /** Name of the stored session used (e.g. `"My Amazon Prime"`). */
  byos_session_name?: string | null;
  /** Measured proxy wire bytes this request used. */
  proxy_bytes?: number | null;
  /** Proxy bytes covered by the base price of the tier used. */
  included_bytes?: number | null;
  /** Started MiB above the included bytes that were surcharged. */
  billed_extra_mib?: number | null;
  /** Byte surcharge debited at settlement (same unit as `total_credits`). */
  byte_surcharge_credits?: number | null;
}

/**
 * A single image extracted by the `content` format.
 *
 * Returned inside {@link ContentResult.images} when `formats: ["content"]` is requested.
 */
export interface ContentImage {
  /** Absolute URL of the image. */
  url: string;
  /** Alt text, or `null` if absent. */
  alt?: string | null;
  /** Semantic role classified by MediaExtractor. */
  role: "hero" | "content" | "logo" | "unknown";
}

/**
 * A single link extracted by the `content` format.
 *
 * Returned inside {@link ContentResult.links} when `formats: ["content"]` is requested.
 */
export interface ContentLink {
  /** Absolute URL of the link. */
  url: string;
  /** Visible anchor text. */
  text: string;
  /** Semantic role classified by the link classifier. */
  role: "content" | "cta" | "social" | "nav" | "unknown";
}

/**
 * Structured output from `formats: ["content"]`.
 *
 * The `content` format is a deterministic AI/KB pipeline mode that extracts
 * Readability-cleaned markdown alongside structured image context and classified
 * links. A SHA-256 `content_hash` is included for cheap change detection — store
 * it and compare on re-scrapes instead of diffing full bodies.
 *
 * Access from the scrape response via `result.content?.content` when
 * `formats: ["content"]` is requested:
 *
 * ```ts
 * const result = await client.scrape({
 *   url: "https://example.com",
 *   formats: ["content"],
 * });
 * const content = result.content?.content as ContentResult | undefined;
 * console.log(content?.body_markdown);  // Readability markdown
 * console.log(content?.content_hash);   // SHA-256 for change detection
 * ```
 */
export interface ContentResult {
  /** Readability-cleaned markdown of the page body. */
  body_markdown: string;
  /** Hex-encoded SHA-256 of `body_markdown` for change detection. */
  content_hash: string;
  /** Approximate word count of the cleaned body text. */
  word_count: number;
  /** Structured image list classified by MediaExtractor. */
  images: ContentImage[];
  /** Classified link list with semantic roles. */
  links: ContentLink[];
}

/** Filter options for json_v2 section tree output. */
export interface SectionFilter {
  /** Minimum content blocks for a section to be included (default 0). */
  min_content_blocks?: number;
  /** Content types to exclude (paragraph, list, table, image, code, blockquote, dl, details). */
  exclude_content_types?: string[];
  /** Strip headings, keep only content blocks (default false). */
  content_only?: boolean;
}

/**
 * Geo-targeting configuration for localized scraping.
 *
 * Routes the request through a proxy in the specified country and/or sets
 * the Accept-Language header and browser locale to match. At least one of
 * `country` or `language` must be provided — the API rejects requests where
 * both are omitted.
 *
 * Common usage patterns:
 * - Country + language: `{ country: "DE", language: "de" }` — proxy in Germany, German locale
 * - Country only: `{ country: "DE" }` — proxy in Germany, country's default language
 * - Language only: `{ language: "de" }` — German Accept-Language header, no country proxy routing
 */
export interface LocationConfig {
  /** ISO 3166-1 alpha-2 country code (e.g., "US", "DE", "JP"). Routes the request through a proxy in that country. At least one of `country` or `language` is required. */
  country?: string;
  /** ISO 639-1 language code (e.g., "en", "de", "ja"). Sets Accept-Language header and browser locale. Defaults to the country's primary language if country is provided and language is omitted. At least one of `country` or `language` is required. */
  language?: string;
}

/** One deterministic extraction selector: exactly one of `css` / `xpath`. */
export interface ExtractionSelector {
  css?: string;
  xpath?: string;
  /** Return this attribute (e.g. `href`) instead of the element text. */
  attr?: string;
  /** Return a list of all matches instead of the first. */
  multiple?: boolean;
}

/** `{field: selector}` map (1-100 fields) for `extraction_selectors`. */
export type ExtractionSelectors = Record<string, ExtractionSelector>;

export interface ScrapeRequest {
  url: string;
  /** Set false to opt out of the recurring-use `suggestions` item on the response. */
  suggestions?: boolean;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  mode?: "auto" | "html" | "js" | "pdf" | "ocr";
  sync?: boolean;
  /** `auto` preserves early async handoff; `wait_until_deadline` waits for completion up to the safe sync deadline. */
  /**
   * Response shape. `"minimal"` returns only content, status, url, cost and
   * warnings; `"full"` keeps the complete payload. When omitted the server
   * chooses (minimal for MCP clients, agent-issued keys and keyless trial keys).
   */
  response?: "full" | "minimal";
  sync_policy?: "auto" | "wait_until_deadline";
  /**
   * `"auto"` renders only pages that need a browser and starts at the lowest
   * tier that returns the page; `true` forces browser rendering (required for
   * `screenshot`, PDF and `actions`).
   */
  render_js?: boolean | "auto";
  screenshot?: boolean;
  markdown?: boolean;
  wait_for?: string;
  /** CSS selector or event to wait for before marking the page as done (e.g. `"networkidle"`). */
  wait_until?: string;
  timeout?: number;
  force_refresh?: boolean;
  /** Cache the response for subsequent identical requests. */
  cache?: boolean;
  /** Cache TTL in seconds (60–86400). Defaults to 3600. Requires `cache: true`. */
  cache_ttl?: number;
  /**
   * Accept a stored result up to this many seconds old (0–86400). `0` always fetches fresh.
   * A hit is billed at 50% of the producing tier's price. When omitted, the API key default applies.
   */
  max_age?: number;
  extraction_schema?: Record<string, unknown>;
  /** Deterministic field extraction evaluated on the fetched HTML; no LLM or BYOK key required. */
  extraction_selectors?: ExtractionSelectors;
  extraction_prompt?: string;
  extraction_profile?: string;
  /**
   * LLM provider to use for extraction. Selects the matching BYOK key registered
   * at /dashboard/settings/llm-keys. When omitted, the most recently used
   * registered key is used automatically.
   */
  extraction_provider?: "openai" | "anthropic" | "openrouter" | "groq";
  /**
   * Per-request LLM model override in provider-specific format (e.g. `'gpt-4o'`,
   * `'claude-opus-4-5-20251101'`, `'llama3-70b-8192'`). When provided, overrides
   * the model saved in your BYOK key settings for this request only. When omitted,
   * the model configured on your registered key is used.
   */
  extraction_model?: string | null;
  /**
   * Shorthand for `extraction_profile`. Selects a pre-built schema template by name.
   * Mutually exclusive with `extraction_profile`.
   */
  extraction_template?:
    | "auto"
    | "product"
    | "article"
    | "job_posting"
    | "faq"
    | "recipe"
    | "event"
    | "ecommerce_homepage"
    | "directory_listing";
  max_credits?: number;
  max_tier?: string;
  /** Cost controls for this request (max_credits, max_tier, force_tier, time_budget, prefer_cost, prefer_speed, fail_fast, fallback_on_block). */
  cost_controls?: {
    max_credits?: number;
    max_tier?: string;
    force_tier?: string;
    /** Total wall-clock budget in seconds for the tier escalation sequence (5–300). */
    time_budget?: number;
    /** Optimize for cost — try cheaper tiers first before escalating. */
    prefer_cost?: boolean;
    /** Optimize for speed — skip to reliable tier immediately. */
    prefer_speed?: boolean;
    /** Return error instead of escalating to more expensive tiers. */
    fail_fast?: boolean;
    /**
     * Opt-in. Applies only when the request forces browser rendering
     * (`render_js: true` or `force_tier: "4"`). If the browser attempt ends in a
     * verification challenge or a timeout, the platform retries once at the
     * dynamic tier (T3/T3.5) and bills the tier that returned the page
     * (`billing.tier_used`). Ignored when actions, screenshot, generate_pdf or
     * ocr are requested. Default: false.
     */
    fallback_on_block?: boolean;
  };
  /** Output formats for content transformation (e.g. `["text", "markdown", "json_v2"]`). */
  formats?: OutputFormat[];
  /** Return the fetched pre-render origin HTML as top-level `raw_html`. `formats: ["html"]` returns the post-render cleaned HTML in `content.html`. */
  include_raw_html?: boolean;
  /** OCR language hint when using `mode: "ocr"` (e.g. `"eng"`, `"deu"`). */
  ocr_language?: string;
  /** PDF page size when rendering with `mode: "pdf"` (e.g. `"A4"`, `"Letter"`). */
  pdf_format?: string;
  /** Promote Schema.org microdata to the top-level `extracted_data` field. */
  promote_schema_org?: boolean;
  /** Filter the extracted content to only return the most relevant sections. */
  filter_content?: boolean;
  /** Embeddings configuration. When enabled, returns vector embeddings of the content. */
  embeddings?: Record<string, unknown>;
  /** Force scroll to load lazy images even when `render_js` is not set. */
  enable_scroll?: boolean;
  /** Include evidence snippets alongside extracted fields. */
  evidence?: boolean;
  /** Webhook URL to receive `job.completed`/`job.failed` events (async mode). */
  webhook_url?: string;
  /** UUID of a stored session integration for authenticated scraping. Mutually exclusive with `cookies`. */
  sessionId?: string;
  /** Inline cookies for one-off authenticated scraping (not stored). Mutually exclusive with `sessionId`. */
  cookies?: Record<string, string>;
  /** Scroll page to trigger lazy-loaded content (requires render_js). */
  scroll_to_load?: boolean;
  /** Number of scroll iterations when scroll_to_load is enabled (1-10, default 3). */
  scroll_count?: number;
  /** Filter options for json_v2 section tree output. */
  section_filter?: SectionFilter;
  /**
   * Inline iframe content into the main document (free, requires render_js).
   * Same-origin iframes are read directly; cross-origin iframes are marked but not fetched.
   */
  include_iframes?: boolean;
  /**
   * Flatten Shadow DOM roots into regular DOM for extraction (free, requires render_js).
   * Web Components with shadow roots become visible in the serialized HTML.
   */
  flatten_shadow_dom?: boolean;
  /**
   * Skip image downloads during browser rendering to reduce proxy bandwidth.
   *
   * - `true` — browser aborts image requests; `<img>` src URLs remain in the DOM so HTML
   *   and text extraction are unaffected, but image bytes are not downloaded.
   * - `false` — all images are downloaded (higher bandwidth, needed for visual accuracy).
   * - `null` / omitted — use the per-domain playbook default (most domains default to `true`;
   *   e-commerce domains such as amazon.com default to `false` because their anti-bot systems
   *   monitor resource-loading patterns).
   *
   * Note: `screenshot` and `generate_pdf` always download images regardless of this setting.
   */
  block_images?: boolean | null;
  /**
   * Browser automation sequence to execute after page load (max 20 actions).
   * Requires render_js. Actions execute sequentially; failed actions are skipped.
   * Results returned in action_results (each with duration_ms). Supported types:
   * wait, wait_for, click, fill, press, scroll, infinite_scroll, screenshot,
   * evaluate, dismiss_consent, select, hover, click_text, extract, check,
   * uncheck, wait_event. `wait_for` accepts `state` (visible, hidden, attached,
   * detached); `press` accepts an optional `selector`. Selectors are CSS, or
   * XPath when prefixed with `//` or `xpath=`. `extract` returns its value in
   * `action_results[i].result`. Every action accepts `optional` (default true;
   * false marks it required, see `actions_on_error`), and click/fill/evaluate
   * accept `timeout_ms` (100-30000, default 10000).
   * Build them with the `Actions` helpers or as `ScrapeAction` object literals.
   *
   * @example
   * [
   *   Actions.wait({ milliseconds: 1000 }),
   *   { type: "click", selector: "button.load-more", optional: false },
   *   { type: "scroll", direction: "down", amount: 3 },
   *   { type: "evaluate", script: "document.title", timeout_ms: 5000 },
   *   Actions.screenshot(),
   *   Actions.select("select#size", { label: "M" }),
   *   Actions.waitFor(".spinner", { state: "hidden" }),
   *   Actions.extract("span.price"),
   * ]
   */
  actions?: ScrapeAction[];
  /**
   * What a failed required action (`optional: false`) does: "continue" (API
   * default) skips it like an optional one; "abort" skips the remaining actions
   * and fails the request with error_code "browser_actions_aborted" (not charged).
   */
  actions_on_error?: "continue" | "abort";
  /**
   * Inline auth headers (e.g. Authorization: Bearer token).
   * Merged with session headers when sessionId is also provided.
   */
  session_headers?: Record<string, string>;
  /**
   * Custom HTTP request headers to forward to the target URL (max 50 headers).
   * Header names must be 1–256 characters; values must be at most 8192 characters.
   * Hop-by-hop and connection-control headers (e.g. `Connection`, `Transfer-Encoding`)
   * are rejected by the API.
   *
   * @example
   * { "Authorization": "Bearer token", "X-Custom-Header": "value" }
   */
  headers?: Record<string, string>;
  /**
   * Opt-in, opaque text describing what the calling agent is trying to do with
   * this request. Sent as the `X-Agent-Intent` header to the AlterLab API
   * itself (not forwarded to the target URL). Independent of `agentContext`/
   * `agentFeedback` — any subset may be sent. Truncated server-side at 500
   * characters; never rejected. Not parsed or interpreted, purely a telemetry
   * signal. Non-ASCII text (accents, emoji, non-Latin scripts) is
   * percent-encoded before being sent as an HTTP header, since header values
   * must be US-ASCII; ASCII-only text is sent unmodified.
   */
  agentIntent?: string;
  /**
   * Opt-in, opaque text describing the broader context for this request (e.g.
   * prior steps taken). Sent as the `X-Agent-Context` header. Same
   * truncation, independence, and non-ASCII encoding rules as `agentIntent`.
   */
  agentContext?: string;
  /**
   * Opt-in, opaque text describing what already failed or what feedback the
   * agent has from a previous attempt. Sent as the `X-Agent-Feedback` header.
   * Same truncation, independence, and non-ASCII encoding rules as
   * `agentIntent`.
   *
   * @example
   * const result = await client.scrape({
   *   url: "https://example.com/product",
   *   agentIntent: "Extract product price for comparison shopping",
   *   agentFeedback: "Previous attempt returned stale cached price",
   * });
   */
  agentFeedback?: string;
  /**
   * Opt-in output profile for LLM agents. `"agent"` compacts the markdown
   * format: images collapse to alt text and repeated link targets keep only
   * their text. When omitted the response is unchanged.
   */
  agent_profile?: "agent";
  /** Token budget (1-200000) for the markdown format when `agent_profile` is `"agent"`. Ignored otherwise. */
  max_tokens?: number;
  /**
   * x402 v2 PaymentPayload (base64-encoded JSON) for keyless pay-per-request
   * callers. Sent as the `PAYMENT-SIGNATURE` header, never in the JSON body.
   */
  paymentSignature?: string;
  /** Use your own integrated proxy instead of the system proxy. */
  use_own_proxy?: boolean;
  /** Override your default proxy integration and use AlterLab's system proxy instead. */
  use_system_proxy?: boolean;
  /** Specific proxy integration ID to use (requires use_own_proxy=true). */
  proxy_integration_id?: string;
  /**
   * ISO 3166-1 alpha-2 country code for geo-targeted proxy routing (e.g., `"US"`, `"DE"`, `"GB"`).
   * The API validates this value against a supported-countries allowlist — unsupported codes
   * return HTTP 422. Common supported codes include major markets: US, GB, DE, FR, IT, ES, NL,
   * CA, JP, SG, AU, BR, IN, and 140+ others. Pass `undefined` for automatic country selection.
   */
  proxy_country?: string;
  /**
   * Customer-facing sticky-session handle. Two separate `scrape()` calls that pass the same
   * `sticky_session` value are pinned to the SAME exit IP and automatically share the cookies
   * captured on the first call (see `captured_cookies` on the response), for the handle's TTL.
   * Enables stateful multi-request flows — e.g. request 1 loads a page, request 2 fetches the
   * captcha/image that appeared using request 1's IP + cookie jar. Requires a paid plan (growth
   * tier or above; the API returns HTTP 403 `STICKY_SESSION_REQUIRES_PLAN` otherwise).
   * Must be 1–128 characters of letters, digits, `-` or `_` only.
   */
  sticky_session?: string;
  /**
   * Sticky-session lifetime in seconds (300–7200, default 1800 applied server-side). Captured
   * cookies bound to `sticky_session` are held for this window, after which the handle resolves
   * to a fresh IP/jar. Ignored unless `sticky_session` is set.
   */
  sticky_session_ttl?: number;
  /**
   * TLS certificate verification. Leave unset (recommended): certificates are verified, and if a
   * site's own certificate is invalid (expired, self-signed, wrong hostname, incomplete chain) the
   * page is still fetched without verification. `true` skips verification from the start. `false`
   * always requires a valid certificate; such sites then fail.
   */
  skip_tls_verification?: boolean;
  /**
   * Remove cookie consent banners from HTML before content extraction (free, enabled by default).
   * Set to `false` to preserve cookie banners in the extracted content.
   */
  remove_cookie_banners?: boolean;
  /**
   * Soft cap on raw response body size in bytes.
   * When the downloaded HTML exceeds this value it is truncated before extraction
   * and `content_truncated.truncation_reason` is set to `"response_body_cap"`.
   *
   * - Default: `5242880` (5 MB)
   * - Set to `0` for no limit
   * - Maximum: `52428800` (50 MB)
   */
  max_response_bytes?: number;
  /**
   * Scrape template slug. When provided, the server looks up the template by
   * slug and merges its `request_config` into the request body before processing.
   * Caller-provided fields take precedence over template defaults.
   *
   * Sent as a query parameter (`?template=slug`), not in the request body.
   *
   * @example
   * ```ts
   * await client.scrape({ url: "https://amazon.com/dp/B0001", template: "amazon-product" });
   * ```
   */
  template?: string;
  /**
   * Geo-targeting configuration. Routes the request through a proxy in the specified country
   * and sets Accept-Language / browser locale for localized content.
   *
   * @example
   * ```ts
   * await client.scrape({ url: "https://example.de", location: { country: "DE", language: "de" } });
   * ```
   */
  location?: LocationConfig;
  /**
   * HTTP method to use when fetching the target URL. Defaults to `"GET"`.
   *
   * Use `"POST"` for REST APIs, GraphQL endpoints, and form submissions. Non-GET
   * methods should be accompanied by a `body` field.
   *
   * Supported values: `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"`.
   * `"DELETE"` relays the method to the target server. Only use on endpoints you own or have explicit permission to modify.
   *
   * @default "GET"
   */
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /**
   * Request body to send with non-GET HTTP methods. Must be a string — serialize
   * objects with `JSON.stringify()` before passing. Ignored when `method` is `"GET"`.
   *
   * @example
   * ```ts
   * await client.scrape({
   *   url: "https://api.example.com/graphql",
   *   method: "POST",
   *   body: JSON.stringify({ query: "{ user { id name } }", variables: { id: 1 } }),
   *   content_type: "application/json",
   * });
   * ```
   */
  body?: string;
  /**
   * Content-Type header for the request body. Defaults to `"application/json"` when
   * `body` is provided. Ignored when `body` is not set.
   *
   * - `"application/json"` — GraphQL, REST API payloads (default)
   * - `"application/x-www-form-urlencoded"` — HTML form submissions
   * - `"text/plain"` — plain text payloads
   *
   * @example
   * ```ts
   * await client.scrape({
   *   url: "https://example.com/login",
   *   method: "POST",
   *   body: "username=alice&password=secret",
   *   content_type: "application/x-www-form-urlencoded",
   * });
   * ```
   */
  content_type?:
    | "application/json"
    | "application/x-www-form-urlencoded"
    | "text/plain"
    | "application/graphql";
}

/**
 * The 202 envelope returned when a scrape is accepted as an async job
 * (`sync: false`). Poll `job_id` with `getJobStatus()` / `waitForJob()`.
 */
export interface ScrapeAcceptedResponse {
  job_id: string;
  status?: string;
  poll_url?: string;
  [key: string]: unknown;
}

/**
 * The 202 envelope the API sends when a synchronous scrape ran past its
 * window. `scrape()` follows it automatically and resolves to the real
 * `ScrapeResponse`; this type describes the raw body for callers using
 * `scrape({ sync: false })` or the raw HTTP API. Credits stay held until the
 * job completes.
 */
export interface SyncDowngradedResponse extends ScrapeAcceptedResponse {
  sync_downgraded: true;
  reason?: string;
  credits_status?: string;
}

/** A pointer to an existing feature that fits the scraped page (#40356). */
export interface DiscoveryHint {
  /** Output format to request, e.g. `json_v2`. */
  format: string;
  /** Why this format fits the page that was just scraped. */
  why: string;
}

/** Recurring-use suggestion (#40690): `create` is the exact body for `endpoint`; never auto-created. */
export interface RecurringSuggestion {
  type: "schedule" | "crawl";
  reason: string;
  tool?: string | null;
  endpoint: string;
  create: Record<string, unknown>;
  estimated_run_cost_microcents: number;
  estimated_monthly_cost_microcents: number;
  docs_url: string;
}

export interface ScrapeResponse {
  /** At most one schedule or crawl suggestion; present only for a recurring-looking series. */
  suggestions?: RecurringSuggestion[] | null;
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  url: string;
  /** Machine-readable warnings, e.g. `requested_option_ignored` or `raw_html_truncated`. */
  warnings?: Array<Record<string, string>> | null;
  /**
   * Source citation to keep when presenting results. Present for free, trial and keyless
   * usage; omitted for paid accounts unless enabled in settings. Never alters `content`.
   */
  attribution?: { text: string; url: string };
  /**
   * The URL after all redirects resolved. Equals `url` when no redirect occurred
   * or when `follow_redirects` is false.
   */
  final_url?: string;
  /**
   * True if the scraper followed one or more redirects before reaching the final page
   * (`final_url !== url`). False when no redirect occurred.
   */
  redirected?: boolean;
  /**
   * Ordered list of redirect hops. Each entry has `url` (string) and `status_code`
   * (number). Populated for T1–T3 tiers when redirects occur. Null when no redirects
   * occurred or when using the T4 (browser) tier.
   */
  redirect_chain?: Array<{ url: string; status_code: number }> | null;
  status_code: number;
  /**
   * Per-tier upstream HTTP status code trail, keyed by tier string (e.g. `"1"`,
   * `"3"`, `"3.5"`, `"4"`). Reflects the upstream response status observed at
   * each tier attempted during auto-escalation. Null when no tier-attempt
   * diagnostics were recorded for this job.
   */
  tier_status_codes?: Record<string, number> | null;
  /**
   * Response content. When `formats` is requested, this is a `Record<string, unknown>`
   * keyed by format name (e.g. `{ markdown: "...", content: ContentResult }`).
   * When no `formats` are requested, this is a plain `string`.
   */
  content: string | Record<string, unknown>;
  html?: string;
  markdown?: string;
  headers: Record<string, string>;
  cached: boolean;
  credits_used: number;
  response_time_ms: number;
  size_bytes: number;
  tier_used?: string;
  screenshot_url?: string;
  /** Absolute, host-qualified URL of the generated PDF when `generate_pdf`/`mode: "pdf"` was requested. */
  pdf_url?: string;
  extracted_data?: Record<string, unknown>;
  /**
   * LLM-extracted structured data matching the `extraction_schema` provided in the request.
   * Present when `extraction_schema` was supplied and extraction succeeded.
   */
  extraction_result?: Record<string, unknown>;
  filtered_content?: Record<string, unknown>;
  byos_applied?: boolean;
  /** Actionable warning when auto-escalation occurred or content quality is low. */
  warning?: string;
  /**
   * Structured tier mismatch detail when `max_tier` or `force_tier` is below
   * the domain's playbook minimum. Contains `domain_min_tier` (number) and
   * either `your_max_tier` (number) or `your_force_tier` (number).
   */
  tier_cap_warning?: Record<string, unknown>;
  /** Content quality metadata from scrape diagnostics. */
  content_quality?: Record<string, unknown>;
  /**
   * Human-readable warning when the target domain has a low historical success
   * rate. The scrape will still proceed, but results may be unreliable.
   * See `domain_difficulty` for structured detail.
   */
  domain_warning?: string;
  /**
   * Structured domain difficulty detail when `domain_warning` is set.
   * Contains: `success_rate` (number 0.0–1.0), `total_attempts` (number),
   * `override_active` (boolean).
   */
  domain_difficulty?: Record<string, unknown>;
  /** Advisory note (e.g. repeat-request detection hint). */
  note?: string | null;
  /**
   * Present when post-hoc soft-block detection fired on a successful scrape but
   * the response contains usable content (`word_count > 100`). Full rate applies —
   * AlterLab paid proxy/compute cost and the content is usable.
   * Always contains: `code` (string, always `'soft_block_posthoc'`), `reason` (string),
   * `word_count` (number), `content_size_bytes` (number).
   * Null for the majority of scrapes where no post-hoc soft-block was detected.
   */
  quality_warning?: Record<string, unknown> | null;
  /** Full billing breakdown for this request, including tier used and escalation history. */
  billing?: BillingDetails;
  /**
   * Cookies set by the target during this scrape (the Set-Cookie jar), returned only when a
   * `sticky_session` handle is used (see `sticky_session` in the scrape options). A subsequent
   * `scrape()` call with the same `sticky_session` automatically replays these cookies (they are
   * persisted server-side for the handle's TTL), so you rarely need to read them directly — they
   * are surfaced for transparency and manual replay.
   */
  captured_cookies?: Record<string, string>;
  /**
   * Attribution metadata identifying AlterLab as the data provider.
   * Auto-populated on every scrape response. Serialized as `_meta` in JSON.
   */
  _meta?: ResponseMeta;
  /** API response envelope version (default `"v1"`). The json_v2 content schema version is in `content.json_v2.version`. */
  version?: string;
  /** Job ID for this scrape request. */
  job_id?: string | null;
  /** Page title. */
  title?: string | null;
  /** Page author, when detected. */
  author?: string | null;
  /** Publication date, when detected. */
  published_at?: string | null;
  /** Page metadata (OG tags, JSON-LD, etc.). */
  metadata?: Record<string, unknown> | null;
  /** Unmodified page HTML. */
  raw_html?: string | null;
  /**
   * Response body returned byte-for-byte with no transformation (when `formats` includes
   * `"raw"`). Compact JSON string for JSON APIs; full HTML for HTML pages.
   */
  raw?: string | null;
  /** Structured content blocks extracted from the page. */
  structured_content?: Array<Record<string, unknown>> | null;
  /** Structured page sections extracted from the page. */
  structured_sections?: Array<Record<string, unknown>> | null;
  /** OCR results for images on the page (OCR mode). */
  ocr_results?: Array<Record<string, unknown>> | null;
  /** Method used for JSON extraction (default `"algorithmic"`). */
  extraction_method?: string | null;
  /** Provider, model, tokens and confidence for LLM extraction. */
  method_details?: Record<string, unknown> | null;
  /**
   * Score 0.0–1.0 indicating how complete the extracted content is. Auth-gated pages
   * typically score 0.1–0.3 (metadata only).
   */
  extraction_completeness?: number | null;
  /** Human-readable note about content extraction limitations. */
  extraction_note?: string | null;
  /**
   * True if the page requires authentication for full content. Partial metadata
   * (OG tags, JSON-LD) is returned instead.
   */
  is_gated?: boolean;
  /**
   * 16-character truncated SHA-256 of the extracted text content. Identical hash across
   * requests means no meaningful content change.
   */
  content_hash?: string | null;
  /** Present when the page content was truncated before extraction due to size limits. */
  content_truncated?: ContentTruncationInfo | null;
  /** ISO timestamp when the result was cached. */
  cached_at?: string | null;
  /** Seconds since the original fetch (0 for a fresh fetch). */
  age_seconds?: number | null;
  /** ISO timestamp of the original fetch that produced this result. */
  fetched_at?: string | null;
  /** Tier that produced the result (for a hit: the stored result's tier). */
  cache_tier?: string | null;
  /** Why a stored result was served when `cached` is true (the max_age in effect and whether it came from the request or the API key default). */
  cache_reason?: string | null;
  /** ISO timestamp when the cache entry expires. */
  expires_at?: string | null;
  /** True if this result was served from stale cache after a scrape failure. */
  stale_cache?: boolean;
  /** True when the origin answered a conditional request with 304 Not Modified and the stored body was served instead of a full fetch. Always false with `force_refresh: true`. */
  revalidated?: boolean;
  /** Your proxy integration info when BYOP was used: `{ id, provider, name }`. */
  proxy_used?: Record<string, unknown> | null;
  /** Results of browser automation actions, when `actions` were provided. */
  action_results?: ActionResult[] | null;
  /**
   * Outcome of the action sequence: "complete", "partial" (an action failed and
   * was skipped) or "aborted" (a required action failed under
   * `actions_on_error: "abort"`). Null without actions.
   */
  actions_status?: "complete" | "partial" | "aborted" | null;
  /** Embedding vectors for the scraped content, when embeddings were enabled. */
  embeddings?: EmbeddingsResult | null;
  /**
   * Set when embeddings were requested but generation failed after a key
   * resolved (invalid key, quota, provider error). The scrape result is still
   * returned and the embeddings add-on is not charged.
   */
  embeddings_error?: EmbeddingsError | null;
  /** Discovery hints, e.g. `[{ format: "json_v2", why: "..." }]`. Omitted when none. */
  hints?: DiscoveryHint[] | null;
}

/** Result of a single browser action execution. */
export interface ActionResult {
  /** Action index in the sequence (0-based). */
  index: number;
  /** Action type that was executed. */
  type: string;
  /** Whether the action completed successfully. */
  success: boolean;
  /** Error message if the action failed. */
  error?: string | null;
  /** Return value (for `evaluate` and `extract` actions). */
  result?: string | null;
  /** Base64-encoded screenshot (legacy; screenshot actions now return `screenshot_url`). */
  screenshot?: string | null;
  /** Public URL of the stored screenshot (for `screenshot` actions). */
  screenshot_url?: string | null;
  /** Public URL of the stored HTML/markdown snapshot (for `snapshot` actions). */
  snapshot_url?: string | null;
  /** Privately stored file metadata (for `download` actions). */
  artifact?: ArtifactMetadata | null;
  /** All captured files of a multi-file `download` action (`max_files` > 1). */
  artifacts?: ArtifactMetadata[] | null;
  /** The ZIP of a multi-file `download` action with `bundle: "zip"`. */
  bundle?: ArtifactMetadata | null;
  /** Delivery outcome (for `download` actions that named an `integration_id`). */
  delivery?: ArtifactDelivery | null;
  /** Page state after the action settled (only for actions sent with `observe: true`). */
  observation?: ActionObservation | null;
  /** Capped element map: viewport, page, total, truncated and elements (for `inspect` actions). */
  element_map?: Record<string, unknown> | null;
  /** True when a snapshot or element map was cut at the size cap. */
  truncated?: boolean | null;
  /** Wall time of this action in ms (0 when it did not run). */
  duration_ms?: number | null;
}

/** Truncation metadata, present when a page exceeded size caps before extraction. */
export interface ContentTruncationInfo {
  /** Always `true` when this object is present. */
  truncated: boolean;
  /** Number of bytes at which the content was cut before processing. */
  truncated_at_bytes: number;
  /** Original content size in bytes before truncation. */
  original_size_bytes: number;
  /** Which size cap caused the truncation. */
  truncation_reason:
    "readability_input_cap" | "readability_output_cap" | "response_body_cap";
}

/** A single embedded chunk of text. */
export interface EmbeddingChunk {
  /** The chunk text that was embedded. */
  text: string;
  /** The embedding vector. */
  embedding: number[];
  /** Character start index in the original text. */
  start_index: number;
  /** Character end index in the original text. */
  end_index: number;
}

/** Why embeddings were requested but not returned (key or provider failure). */
export interface EmbeddingsError {
  /** Machine-readable failure code. */
  code: "no_api_key" | "invalid_key" | "quota" | "provider_error";
  /** Human-readable explanation. */
  message: string;
}

/** Embeddings result included in a scrape response. */
export interface EmbeddingsResult {
  /** Embedding model used. */
  model: string;
  /** Embedding vector dimensions. */
  dimensions: number;
  /** Embedded text chunks. */
  chunks: EmbeddingChunk[];
  /** Total tokens processed by the embedding model. */
  total_tokens: number;
  /** Number of chunks generated. */
  total_chunks: number;
  /** Whether embeddings were served from cache. */
  cached?: boolean;
}

/**
 * Attribution metadata included in all scrape responses.
 *
 * Identifies the data provider and API version that produced the response.
 * Always present with default values (`"alterlab.io"` / `"v1"`).
 */
export interface ResponseMeta {
  /** Data provider identifier (always `"alterlab.io"`). */
  provider: string;
  /** API version that produced this response (e.g. `"v1"`). */
  api_version: string;
}

/**
 * Rate-limit tier information derived from account balance.
 *
 * Returned as part of the `/auth/me` response. Use this to display the user's
 * current tier and the balance threshold needed to reach the next tier.
 *
 * Balance-based tier table:
 *
 * | Tier        | Balance    | RPM   | Concurrent |
 * |-------------|------------|-------|------------|
 * | Free        | $0–$5      | 30    | 3          |
 * | Basic       | $5–$50     | 3000  | 10         |
 * | Growth      | $50–$200   | 3000  | 15         |
 * | Scale       | $200–$500  | 3000  | 25         |
 * | High Volume | $500+      | 3000  | 50         |
 * | Enterprise  | Custom     | 10000 | 500        |
 */
export interface TierInfo {
  /** Human-readable tier name, e.g. `"Free"`, `"Basic"`, `"Growth"`. */
  name: string;
  /** Machine-readable tier identifier, e.g. `"free"`, `"basic"`, `"growth"`. */
  slug: string;
  /**
   * Sustained write (submission) rate enforced at this tier, per minute. Paid tiers are
   * enforced at least 3000/min; `GET /api/v1/usage/limits` is the authoritative view.
   */
  requests_per_minute: number;
  /** Per-minute budget of the separate read/poll bucket. */
  rpm_read?: number;
  /** Maximum number of concurrent scrape requests allowed at this tier. */
  concurrent_requests: number;
  /** Minimum account balance (USD) required to qualify for this tier. */
  min_balance_usd: number;
  /** Upper balance threshold (USD) for this tier. `null` means no upper limit. */
  max_balance_usd: number | null;
  /** Slug of the next higher tier, or `null` if already at the top tier. */
  next_tier_slug: string | null;
  /** Balance (USD) needed to reach the next tier, or `null` if at top tier. */
  next_tier_threshold_usd: number | null;
}

export interface UsageStats {
  /** Current non-expiring PAYG wallet balance in microcents. */
  balance_microcents: number;
  /** @deprecated Use balance_microcents. */
  credits_available: number;
  /** Actual microcents spent in the current month. */
  credits_used_month: number;
  /** Canonical balance tier slug. */
  account_tier: string;
  /** Source of the account entitlement. */
  entitlement_source: string;
  period_start: string;
  period_end: string;
  /** Set when the response is filtered to one request tag. */
  tag?: string | null;
  /** Billed spend of the tag in microcents (successful rows only). */
  tag_spent_microcents?: number | null;
  /** Rows tracked for the tag. */
  tag_requests?: number | null;
  tag_succeeded?: number | null;
  tag_failed?: number | null;
}

export interface CrawlAdvancedOptions {
  /** `true` always renders, `"auto"` renders only JS-heavy pages. */
  renderJs?: boolean | "auto";
  screenshot?: boolean;
  useProxy?: boolean;
  waitFor?: string;
  timeout?: number;
  /** Scroll page to trigger lazy-loaded content (requires renderJs). */
  scrollToLoad?: boolean;
  /** Number of scroll iterations when scrollToLoad is enabled (1-10, default 3). */
  scrollCount?: number;
  /** Filter options for json_v2 section tree output. */
  sectionFilter?: SectionFilter;
}

export interface CrawlRequest {
  url: string;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  /** Approval id returned with `pending_approval`; resubmit the identical request with it once the spend is approved. */
  approvalId?: string;
  /** Return a free cost estimate (see `DryRunEstimate`) without dispatching, debiting or reserving anything. */
  dryRun?: boolean;
  maxPages?: number;
  maxDepth?: number;
  includePatterns?: string[];
  excludePatterns?: string[];
  formats?: OutputFormat[];
  extractionSchema?: Record<string, unknown>;
  extractionProfile?: string;
  /**
   * Shorthand for `extractionProfile`. Selects a pre-built schema template by name.
   * Mutually exclusive with `extractionProfile`.
   */
  extractionTemplate?:
    | "auto"
    | "product"
    | "article"
    | "job_posting"
    | "faq"
    | "recipe"
    | "event"
    | "ecommerce_homepage"
    | "directory_listing";
  /**
   * LLM provider to use for extraction on each crawled page. Selects the matching
   * BYOK key registered at /dashboard/settings/llm-keys. When omitted, the most
   * recently used registered key is used automatically.
   */
  extractionProvider?: "openai" | "anthropic" | "openrouter" | "groq";
  /**
   * Per-crawl LLM model override in provider-specific format (e.g. `'gpt-4o'`,
   * `'llama3-70b-8192'`). Applied to every page in the crawl. When omitted,
   * the model configured on your registered BYOK key is used.
   */
  extractionModel?: string | null;
  webhookUrl?: string;
  respectRobots?: boolean;
  includeSubdomains?: boolean;
  costControls?: {
    maxCredits?: number;
    maxTier?: string;
    forceTier?: string;
    /** Total wall-clock budget in seconds for the tier escalation sequence (5–300). */
    timeBudget?: number;
    /** Optimize for cost — try cheaper tiers first before escalating. */
    preferCost?: boolean;
    /** Optimize for speed — skip to reliable tier immediately. */
    preferSpeed?: boolean;
    /** Return error instead of escalating to more expensive tiers. */
    failFast?: boolean;
  };
  advanced?: CrawlAdvancedOptions;
  /** Force-refresh cached pages during the crawl. */
  forceRefresh?: boolean;
  /** Credit or page budget to cap the crawl (stop when exhausted). */
  budget?: Record<string, unknown>;
  /** Cache crawled pages for repeated runs. */
  cache?: boolean;
  /** Cache TTL in seconds for crawled pages. */
  cacheTtl?: number;
  /** Enable change-tracking: only re-process pages whose content changed since last crawl. */
  changeTracking?: Record<string, unknown>;
  /** Extraction configuration to apply per page (alternative to extractionSchema). */
  extraction?: Record<string, unknown>;
  /** Maximum number of concurrent browser instances (affects cost and speed). */
  maxConcurrency?: number;
  /** Output destination for crawl results (e.g. S3, webhook). */
  output?: Record<string, unknown>;
  /** Crawl priority relative to other active crawls (higher = processed sooner). */
  priority?: number;
  /** Sitemap discovery strategy: `"skip"` | `"include"` | `"only"`. */
  sitemap?: "skip" | "include" | "only";
  /** Path to the sitemap file (e.g. `/sitemap.xml`). Overrides auto-discovery. */
  sitemapPath?: string;
  /** Result storage configuration (persist crawl output to external storage). */
  storage?: Record<string, unknown>;
  /**
   * Webhook configuration for real-time page-level events.
   * Alternative to `webhookUrl` — use when you need per-event metadata.
   */
  webhook?: Record<string, unknown>;
  /**
   * Custom HTTP headers to forward to each scraped page during the crawl (max 50 headers).
   *
   * @example
   * { "Authorization": "Bearer token", "X-Custom-Header": "value" }
   */
  headers?: Record<string, string>;
  /** Embeddings configuration. When enabled, each scraped page is chunked and embedded (+$0.001 per page). */
  embeddings?: {
    enabled?: boolean;
    model?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  };
  /**
   * Paginated list crawl: fetches `url_template` page by page (no link following) until
   * `stop_when`, `max_pages`, `max_credits` or an error stops it. Billed per page fetched.
   */
  list?: CrawlListConfig;
}

/** Paginated list crawl configuration (`list` on a crawl request). */
export interface CrawlListConfig {
  /** URL containing a `{page}` placeholder. */
  url_template: string;
  /** First page number (default 1). */
  start?: number;
  /** Hard ceiling on pages fetched (default 50). */
  max_pages?: number;
  /** Item identity: `"url"`, `"jsonld:@id"` or `"selector:<css>"` (default `"url"`). */
  item_key?: string;
  stop_when?: { no_new_items?: number };
}

export interface CrawlResponse {
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  crawl_id: string;
  status: string;
  estimated_pages: number;
  total_enqueued: number;
  estimated_credits: number;
  /** True for list crawls: estimates are a ceiling; only fetched pages are charged. */
  estimate_is_ceiling?: boolean;
  message: string;
  /**
   * Effective storage backend for this crawl (default `"redis"`). `"redis"` = inline
   * results, `"s3"`/`"r2"` = presigned download URL on completion. May differ from the
   * requested storage if auto-upgraded or if cloud storage was unavailable.
   */
  storage?: string;
  /** Maximum concurrent crawl sessions allowed for your balance tier. */
  crawl_slot_limit?: number | null;
  /**
   * Balance tier used to determine the crawl slot limit: one of `"free"`, `"basic"`,
   * `"growth"`, `"scale"`, `"high_volume"`.
   */
  crawl_slot_tier?: string | null;
  /** Actual max concurrency applied to this crawl (may be capped by your plan tier). */
  effective_max_concurrency?: number | null;
}

/** Per-depth-level analytics for a crawl. */
export interface CrawlDepthStats {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  /** Depth level (0 = start URL). */
  depth: number;
  /** Total pages at this depth. */
  total: number;
  /** Pages that scraped successfully. */
  succeeded?: number;
  /** Pages that failed. */
  failed?: number;
  /** Pages still queued or processing. */
  pending?: number;
  /** Actual credits consumed at this depth (microcents). */
  credits_used?: number;
  /** Pages per tier at this depth, e.g. `{ "1": 5, "3": 2 }`. */
  tier_breakdown?: Record<string, number>;
  /** URLs discovered at this depth (truncated to the first 200). */
  urls?: string[];
}

/** Per-pattern budget usage for a crawl with budget control. */
export interface CrawlBudgetStatus {
  /** Configured budget limits per pattern, e.g. `{ "/products/*": 100, "*": 5 }`. */
  budget: Record<string, number>;
  /** Current page counts per pattern, e.g. `{ "/products/*": 42, "*": 3 }`. */
  counts: Record<string, number>;
  /** Patterns whose budget has been fully used. */
  exhausted?: string[];
}

/** Crawl-level aggregation of page changes (change tracking). */
export interface CrawlChangeSummary {
  /** Pages not seen in the previous crawl. */
  new_pages?: number;
  /** Pages whose content hash changed. */
  changed_pages?: number;
  /** Pages with identical content. */
  unchanged_pages?: number;
  /** Pages present in the previous crawl but missing from the current one. */
  removed_pages?: number;
  /** URLs that were in the previous crawl but not in this one. */
  removed_urls?: string[];
}

/** Output connector status in a crawl status response. */
export interface CrawlOutputStatus {
  /** Connector type: `s3`, `gcs`, or `webhook_stream`. */
  type: string;
  /** Output format (for cloud connectors). */
  format?: string | null;
  /** Number of pages successfully exported. */
  pages_exported?: number;
  /** Number of pages that failed to export. */
  pages_failed?: number;
  /** Total bytes uploaded (for cloud connectors). */
  bytes_uploaded?: number;
  /** Manifest file key/path (set on completion). */
  manifest_url?: string | null;
}

/** Pagination metadata for paginated responses. */
export interface PaginationMeta {
  /** Number of results skipped. */
  offset: number;
  /** Maximum results per page. */
  limit: number;
  /** Total results matching the filter (before pagination). */
  total_matching: number;
  /** Whether more results exist beyond this page. */
  has_more: boolean;
}

export interface CrawlPageResult {
  job_id: string;
  url: string;
  status: string;
  result?: Record<string, unknown>;
  error?: string | Record<string, unknown> | null;
}

export interface CrawlBilling {
  credits_debited: number;
  credits_used: number;
  credits_refunded: number;
  estimated_cost_usd: string;
  actual_cost_usd: string;
  is_byop: boolean;
  tier_breakdown: Record<string, number>;
}

/** Machine-readable next step for a partial or failed crawl. */
export interface CrawlNextAction {
  type: string;
  params?: Record<string, unknown>;
  price_microcents?: number | null;
  docs_url?: string | null;
  [key: string]: unknown;
}

/** Page order for `getCrawl` results. */
export type CrawlPageSort = "depth" | "url" | "completed_at" | "credits";

/** Page pagination, filter and sort options for `getCrawl`. */
export interface GetCrawlOptions {
  /** Max pages per response (1-1000; default: all). */
  limit?: number;
  /** Pages to skip. */
  offset?: number;
  /** Page order (default: depth, i.e. discovery order). */
  sort?: CrawlPageSort;
  /** Only pages with this status. */
  status?: string;
  /** Include per-depth analytics (`depth_stats`) in the response. */
  includeDepthStats?: boolean;
}

export interface CrawlStatusResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  crawl_id: string;
  /** List crawls only: why pagination stopped. */
  stopped_reason?: "no_new_items" | "max_pages" | "budget" | "error" | null;
  /** List crawls only: deduplicated items collected so far. */
  items?: Array<{ key: string; url?: string | null; page: number }> | null;
  /** List crawls only: page a resume would fetch next. */
  next_page?: number | null;
  /**
   * Source citation to keep when presenting results. Present for free, trial and keyless
   * usage; omitted for paid accounts unless enabled in settings. Never alters the data.
   */
  attribution?: { text: string; url: string };
  status:
    | "discovering"
    | "scraping"
    | "completed"
    | "partial"
    | "failed"
    | "cancelled";
  total: number;
  completed: number;
  failed: number;
  in_progress: number;
  credits_debited: number;
  created_at: string;
  current_depth: number;
  max_depth: number;
  total_discovered: number;
  billing?: CrawlBilling;
  pages?: CrawlPageResult[];
  /** Depth levels that currently have pending or in-progress jobs. */
  active_depths?: number[];
  /** Per-depth analytics. Only included when `include_depth_stats=true`. */
  depth_stats?: CrawlDepthStats[] | null;
  /** Per-path budget usage. Only present when a budget was configured. */
  budget_status?: CrawlBudgetStatus | null;
  /**
   * Effective inter-request delay in seconds:
   * `max(user_delay, min(robots_crawl_delay, 10))`.
   */
  effective_crawl_delay?: number;
  /** Pagination metadata. Present when pages are included. */
  pagination?: PaginationMeta | null;
  /**
   * Crawl-level change summary. Only present when change tracking is enabled and the
   * crawl is completed/partial.
   */
  change_summary?: CrawlChangeSummary | null;
  /** Output connector status. Only present when output was configured. */
  output_status?: CrawlOutputStatus | null;
  /**
   * Next step derived from failed pages' evidence. Only present for partial or failed
   * crawls when an action exists.
   */
  next_action?: CrawlNextAction | null;
  /** Storage backend for this crawl's results. Only present when storage is `"s3"` or `"r2"`. */
  storage_backend?: "s3" | "r2" | null;
  /**
   * Presigned download URL for crawl results (JSONL). Only present when `storage_backend`
   * is set and the crawl is completed or partial.
   */
  results_url?: string | null;
  /** ISO 8601 timestamp when `results_url` expires. */
  results_expiry?: string | null;
}

export interface CrawlCancelResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  crawl_id: string;
  /**
   * `"cancelled"` when fully cancelled and refund applied.
   * `"cancellation_pending"` when a concurrent request held the refund lock —
   * the crawl is not yet in a terminal state; retry the cancel to receive credits.
   */
  status: string;
  cancelled_jobs: number;
  credits_refunded: number;
  credits_used: number;
  /**
   * `true` when the refund could not be applied immediately due to a concurrent
   * cancel request. Retry the cancel to receive the outstanding credits.
   * When `true`, `status` will be `"cancellation_pending"`.
   */
  refund_pending: boolean;
  message: string;
}

export interface CrawlExportOptions {
  /**
   * Output format for the export file.
   * - `"json"` — JSON array of page result objects (default)
   * - `"jsonl"` — Newline-delimited JSON (one object per line)
   * - `"csv"` — Comma-separated values
   */
  format?: "json" | "jsonl" | "csv";
  /**
   * Filter pages by status. Defaults to `"succeeded"`.
   * Use `"all"` to include every page regardless of status.
   */
  status?:
    | "succeeded"
    | "failed"
    | "rejected"
    | "expired"
    | "queued"
    | "processing"
    | "cancelled"
    | "all";
  /**
   * Comma-separated list of fields to include in the output
   * (e.g. `"url,html,status"`). Omit to include all fields.
   */
  fields?: string;
}
export interface CrawlSSEEvent {
  event:
    "page.completed" | "page.failed" | "crawl.progress" | "crawl.completed";
  data: Record<string, unknown>;
}

export interface CrawlAndWaitOptions {
  pollInterval?: number;
  pollTimeout?: number;
  backoffMultiplier?: number;
  maxInterval?: number;
}

/**
 * One URL item of a batch (API `BatchItemRequest`).
 *
 * `render_js`, `screenshot`, `markdown`, `use_proxy`, `scroll_to_load`,
 * `scroll_count` and `section_filter` are convenience shorthands that
 * `batchScrape` moves into `advanced`; `max_credits` / `max_tier` move into
 * `cost_controls`. Values set explicitly in `advanced` / `cost_controls` take
 * precedence.
 */
export interface BatchScrapeRequest {
  url: string;
  mode?: "auto" | "html" | "js" | "pdf" | "ocr";
  /** HTTP method for this URL. POST costs 1.5x the base tier price. */
  method?: "GET" | "POST";
  /** Request body for POST (UTF-8 string). */
  body?: string;
  content_type?:
    | "application/json"
    | "application/x-www-form-urlencoded"
    | "text/plain"
    | "application/graphql";
  wait_for?: string;
  timeout?: number;
  cache?: boolean;
  include_raw_html?: boolean;
  location?: LocationConfig;
  formats?: OutputFormat[];
  advanced?: BatchItemAdvancedOptions;
  cost_controls?: Record<string, unknown>;
  extraction_schema?: Record<string, unknown>;
  /** Deterministic field extraction evaluated on the fetched HTML; no LLM or BYOK key required. */
  extraction_selectors?: ExtractionSelectors;
  extraction_prompt?: string;
  extraction_profile?: string;
  extraction_template?: ExtractionProfileName;
  render_js?: boolean | "auto";
  screenshot?: boolean;
  markdown?: boolean;
  /** Proxy intent shorthand; see `BatchItemAdvancedOptions.use_proxy`. */
  use_proxy?: boolean;
  max_credits?: number;
  max_tier?: string;
  /** Scroll page to trigger lazy-loaded content (requires render_js). */
  scroll_to_load?: boolean;
  /** Number of scroll iterations when scroll_to_load is enabled (1-10, default 3). */
  scroll_count?: number;
  /** Filter options for json_v2 section tree output. */
  section_filter?: SectionFilter;
}

/**
 * Advanced options of one batch item (API `AdvancedOptions`). Other API
 * `AdvancedOptions` fields pass through unchanged.
 */
export interface BatchItemAdvancedOptions {
  /**
   * Proxy intent. Leave unset to let the platform route reactively (proxy only
   * when the target needs it); `false` keeps direct routing; `true` routes
   * through the premium proxy. Omission is preserved on the wire (#33552).
   */
  use_proxy?: boolean;
  /** camelCase alias of `use_proxy` (matches `CrawlAdvancedOptions.useProxy`). */
  useProxy?: boolean;
  [key: string]: unknown;
}

/** Cloud storage export for batch results (API `BatchExportConfig`). */
export interface BatchExportConfig {
  /** Storage integration ID to export to. */
  integration_id: string;
  /** Key prefix override (uses the integration default if not set). */
  prefix?: string;
  format?: "jsonl" | "csv" | "json";
}

/** Body of `POST /api/v1/batch` (API `BatchRequest`). */
/** Per-item entry of a dry-run estimate. */
export interface DryRunItem {
  url: string;
  predicted_tier: string;
  estimated_microcents: number;
}

/** Remaining-budget check of a dry-run estimate. */
export interface DryRunBudget {
  limit_type: string | null;
  limit_microcents: number | null;
  remaining_microcents: number | null;
  would_exceed: boolean;
}

/**
 * 202 response of a batch or crawl estimated above the key's `approval_above_usd`:
 * nothing was dispatched or charged. Have the account owner open `approval_url`,
 * poll `GET /api/v1/approvals/{approval_id}` until approved, then resubmit the
 * identical request with `approval_id` (`approvalId` on `crawl()`).
 * `batchScrape()`/`crawl()` keep their declared return types, so cast the result.
 */
export interface PendingApprovalResponse {
  status: "pending_approval";
  approval_id: string;
  endpoint: string;
  estimated_microcents: number;
  estimated_usd: number;
  approval_above_usd: number;
  approval_url: string;
  expires_at: string;
  next_action: Record<string, unknown>;
}

/**
 * Response of a batch or crawl submitted with `dry_run`: nothing was dispatched.
 * `batchScrape()`/`crawl()` keep their declared return types, so cast the result.
 */
export interface DryRunEstimate {
  dry_run: true;
  status: "dry_run";
  item_count: number;
  items: DryRunItem[];
  total_microcents: number;
  total_usd: number;
  estimated_range_microcents: { low: number; high: number };
  estimated_range_usd: { low: number; high: number };
  predicted_seconds: number;
  budget: DryRunBudget;
  notes: Record<string, unknown>;
}

export interface BatchRequest {
  /** URLs to scrape (1-100). */
  urls: BatchScrapeRequest[];
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  /** BYOS session ID applied to every URL; all URLs must match its domain. */
  session_id?: string;
  /** Approval id returned with `pending_approval`; resubmit the identical request with it once the spend is approved. */
  approval_id?: string;
  /** Return a free cost estimate (see `DryRunEstimate`) without dispatching, debiting or reserving anything. */
  dry_run?: boolean;
  /** Cap on concurrent jobs per registrable domain (>= 1); can only lower the adaptive dispatch window. */
  max_in_flight_per_domain?: number;
  /** Queue items over your global or per-domain concurrency limit (default true, up to 15 minutes); false rejects them in `rejected_items`. */
  queue_over_limit?: boolean;
  /** Receives the `batch.completed` event when all jobs finish. */
  webhook_url?: string;
  /** Upload results to cloud storage on batch completion. */
  export?: BatchExportConfig;
  /** Batch-level defaults, overridden by item-level extraction fields. */
  extraction_schema?: Record<string, unknown>;
  /** Deterministic field extraction evaluated on the fetched HTML; no LLM or BYOK key required. */
  extraction_selectors?: ExtractionSelectors;
  extraction_prompt?: string;
  extraction_profile?: ExtractionProfileName;
  /** BYOK provider for extraction; batch-level only (rejected on items). */
  extraction_provider?: "openai" | "anthropic" | "openrouter" | "groq";
}

const BATCH_ITEM_ADVANCED_KEYS = [
  "render_js",
  "screenshot",
  "markdown",
  "use_proxy",
  "scroll_to_load",
  "scroll_count",
  "section_filter",
] as const;
const BATCH_ITEM_COST_CONTROL_KEYS = ["max_credits", "max_tier"] as const;

/**
 * Convert an SDK batch item into the API `BatchItemRequest` shape: the API has
 * no top-level `render_js`/`max_tier`/... on batch items and silently drops
 * them, so move them under `advanced` / `cost_controls` (#34537).
 */
function toBatchItemPayload(item: BatchScrapeRequest): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...item };
  const advanced: Record<string, unknown> = {};
  const costControls: Record<string, unknown> = {};
  for (const key of BATCH_ITEM_ADVANCED_KEYS) {
    if (payload[key] !== undefined) advanced[key] = payload[key];
    delete payload[key];
  }
  for (const key of BATCH_ITEM_COST_CONTROL_KEYS) {
    if (payload[key] !== undefined) costControls[key] = payload[key];
    delete payload[key];
  }
  if (Object.keys(advanced).length > 0 || item.advanced) {
    const { useProxy, ...itemAdvanced } = item.advanced ?? {};
    const merged: Record<string, unknown> = { ...advanced, ...itemAdvanced };
    // The API only knows `use_proxy`; an unset value must stay omitted so the
    // platform keeps reactive proxy routing (#33552).
    const useProxyIntent =
      itemAdvanced.use_proxy ?? useProxy ?? advanced.use_proxy;
    if (useProxyIntent === undefined) {
      delete merged.use_proxy;
    } else {
      merged.use_proxy = useProxyIntent;
    }
    payload.advanced = merged;
  }
  if (Object.keys(costControls).length > 0) {
    payload.cost_controls = { ...costControls, ...item.cost_controls };
  }
  return payload;
}

export interface BatchRejectedItem {
  index: number;
  url: string;
  reason: string;
  scope: string;
  domain?: string | null;
  limit?: number | null;
  retry_after_seconds?: number | null;
}

/** Why one batch item has no job. */
export interface BatchJobRejection {
  scope: string;
  reason: string;
  retry_after_seconds?: number | null;
}

/** Outcome for one submitted batch item, in submission order. */
export interface BatchJobEntry {
  index: number;
  url: string;
  status: "accepted" | "rejected";
  job_id: string | null;
  rejected: BatchJobRejection | null;
}

export interface BatchResponse {
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  batch_id: string;
  total_urls: number;
  /** @deprecated Use total_urls. Retained for clients migrating from <=3.21.3. */
  total_requests?: number;
  estimated_credits: number;
  /** Accepted subset, not positional. Pair ids with URLs through `jobs`. */
  job_ids: string[];
  /** One entry per submitted item, in submission order. */
  jobs: BatchJobEntry[];
  status: string;
  accepted_urls: number;
  rejected_urls: number;
  rejected_items: BatchRejectedItem[];
  byos_applied: boolean;
  byos_session_name?: string | null;
  /** Documentation for partial batch acceptance. Present only when `rejected_items` is non-empty. */
  docs_url?: string | null;
}

// BEGIN GENERATED: output-formats (scripts/generate_output_formats.py; do not edit)
/** Output formats accepted by the `formats` option (mirrors the API schema). */
export type OutputFormat =
  | "text"
  | "json"
  | "json_v2"
  | "html"
  | "markdown"
  | "rag"
  | "content"
  | "raw"
  | "document"
  | "structured_data";
// END GENERATED: output-formats

/**
 * Canonical job-status vocabulary, mirrored from `JobStatus` in
 * `services/api/app/models/job.py` (the server's single source of truth,
 * enforced by a DB CHECK constraint since migration 0263). `succeeded` is
 * the value current worker code writes on completion; `completed` is kept
 * only for backward compatibility with historical rows (migration 0021
 * normalized all `completed` rows to `succeeded` and no current write path
 * produces it) (#31823).
 */
export type JobStatus =
  | "pending"
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "rejected"
  | "cancelled"
  | "completed";

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  result?: ScrapeResponse;
  /** Failure detail: a message or a structured error (may carry `hint`). */
  error?: string | Record<string, unknown>;
  /** Next-step guidance for a failed job (#40689), when sent at job level. */
  next_action?: Record<string, unknown> | null;
  created_at?: string;
  completed_at?: string;
}

/**
 * Body of `POST /api/v1/scrape/estimate`. Mirrors the API's `UnifiedScrapeRequest`
 * so the estimate is computed for exactly the request you intend to submit (#34537).
 */
export interface CostEstimateRequest {
  url: string;
  mode?: "auto" | "html" | "js" | "pdf" | "ocr";
  /** HTTP method for the target request. POST costs 1.5x the base tier price. */
  method?: "GET" | "POST";
  /** Request body for POST (UTF-8 string). */
  body?: string;
  content_type?:
    | "application/json"
    | "application/x-www-form-urlencoded"
    | "text/plain"
    | "application/graphql";
  /** Custom headers forwarded to the target. */
  headers?: Record<string, string>;
  sync?: boolean;
  /**
   * Response shape. `"minimal"` returns only content, status, url, cost and
   * warnings; `"full"` keeps the complete payload. When omitted the server
   * chooses (minimal for MCP clients, agent-issued keys and keyless trial keys).
   */
  response?: "full" | "minimal";
  sync_policy?: "auto" | "wait_until_deadline";
  wait_for?: string;
  wait_until?: string;
  /** Request timeout in seconds (1-300). */
  timeout?: number;
  force_refresh?: boolean;
  cache?: boolean;
  /** Cache TTL in seconds (60-86400). */
  cache_ttl?: number;
  screenshot?: boolean;
  enable_scroll?: boolean;
  include_raw_html?: boolean;
  /** Maximum response size in bytes (0-52428800). */
  max_response_bytes?: number;
  ocr_language?: string;
  pdf_format?: "text" | "markdown";
  promote_schema_org?: boolean;
  filter_content?: boolean;
  /** Include evidence/provenance data in the result. */
  evidence?: boolean;
  location?: LocationConfig;
  embeddings?: {
    enabled?: boolean;
    model?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  };
  extraction_schema?: Record<string, unknown>;
  /** Deterministic field extraction evaluated on the fetched HTML; no LLM or BYOK key required. */
  extraction_selectors?: ExtractionSelectors;
  extraction_prompt?: string;
  extraction_profile?: ExtractionProfileName;
  extraction_template?: ExtractionProfileName;
  extraction_provider?: "openai" | "anthropic" | "openrouter" | "groq";
  extraction_model?: string;
  webhook_url?: string;
  advanced?: Record<string, unknown>;
  cost_controls?: Record<string, unknown>;
  formats?: OutputFormat[];
  /** Opt-in output profile for LLM agents (`"agent"` compacts markdown). */
  agent_profile?: "agent";
  /** Accept a stored result up to this many seconds old (0-86400). */
  max_age?: number;
  /** Token budget (1-200000) for markdown when `agent_profile` is `"agent"`. */
  max_tokens?: number;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
}

/** Pre-built extraction profile / template names accepted by the API. */
export type ExtractionProfileName =
  | "auto"
  | "product"
  | "article"
  | "job_posting"
  | "faq"
  | "recipe"
  | "event"
  | "ecommerce_homepage"
  | "directory_listing";

/** One factor that moved a cost estimate (e.g. render_js, egress, cache). */
export interface EstimateDriver {
  name: string;
  detail: string;
}

export interface CostEstimateResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  url: string;
  estimated_tier: string;
  estimated_credits: number;
  confidence: "low" | "medium" | "high";
  max_possible_credits: number;
  reasoning: string;
  /** Lowest plausible settled cost (same unit as `estimated_credits`). */
  min_credits?: number | null;
  /** Most likely settled cost; equals `estimated_credits`. */
  likely_credits?: number | null;
  /** Highest settled cost for these parameters; equals `max_possible_credits`. */
  max_credits?: number | null;
  /** Request parameters that shaped the range (render_js, egress, add-ons, cache). */
  drivers?: EstimateDriver[];
}

/** Long-poll window (seconds) used after a sync downgrade (#37371). */
const DOWNGRADE_LONG_POLL_SECONDS = 20;

export interface WaitForJobOptions {
  pollInterval?: number;
  pollTimeout?: number;
  backoffMultiplier?: number;
  maxInterval?: number;
  /**
   * Seconds to long-poll `GET /api/v1/jobs/{id}?wait=N` per request (server
   * caps at 25). 0 (default) disables it. `scrape()` enables it after a
   * `sync_downgraded` 202 so the result is collected as soon as it lands.
   */
  serverWait?: number;
}

export interface AlterLabOptions {
  apiKey: string;
  baseUrl?: string;
  maxRetries?: number;
  /** Initial retry delay in ms (jittered exponential backoff). */
  retryDelay?: number;
  /**
   * Maximum total ms one request may spend sleeping between retries
   * (default 60000). When the next wait would exceed it, the last error
   * (e.g. {@link RateLimitError} with `retryAfter`) is thrown instead.
   * `null` disables the cap.
   */
  maxRetryWait?: number | null;
  logger?: Logger;
  /**
   * Opt-in: called when an MCP-parity method (`support`, `jobs`, `monitors`,
   * ...) gets a non-JSON response. It only notifies you; the SDK never files
   * feedback or tickets by itself.
   */
  onUnexpectedResponse?: UnexpectedResponseHook;
}

// ---------------------------------------------------------------------------
// Feedback types
// ---------------------------------------------------------------------------

export interface FeedbackRequest {
  category: string;
  tried?: string;
  happened: string;
  expected?: string;
  jobId?: string;
  /** Tool or endpoint the report is about; sent as `tool_name` (max 100 chars). */
  toolName?: string;
  /** Target URL; sent as `url` (max 2000 chars, only the hostname is stored). */
  url?: string;
  /** Wire-field override for `what_failed`; replaces `[category] happened`. */
  what_failed?: string;
  /** Wire-field override for `what_tried`; replaces `tried` + `job_id`. */
  what_tried?: string;
  /** Wire-field override for `what_expected`; replaces `expected`. */
  what_expected?: string;
  /** What would make AlterLab better; sent as `suggestion` (max 1000 chars). */
  suggestion?: string;
  /** Client surface sent as `surface` for AX metrics; defaults to `"sdk"`. */
  surface?: "mcp" | "api_hint" | "sdk" | "setup";
  /** Only return up to 3 matching clusters; nothing is stored. Exclusive with `same_as`/`new`. */
  dry_run?: boolean;
  /** `cluster_key` of a returned match: counts as a vote instead of filing a new cluster. */
  same_as?: string;
  /** File as a new report even when a close match exists. */
  new?: boolean;
}

export interface FeedbackMatch {
  cluster_key: string;
  status: string;
  public_title?: string;
  message?: string;
  reason?: string;
  fixed_in?: string;
}

export interface FeedbackResponse {
  report_id: string;
  cluster_key: string;
  status: string;
  message?: string;
  /** Up to 3 similar existing clusters. */
  matches?: FeedbackMatch[];
  /** With `same_as`: true when this was a new vote. */
  vote_recorded?: boolean;
  /** GET this URL to follow the report's status. */
  statusUrl: string;
}

// ---------------------------------------------------------------------------
// Search types
// ---------------------------------------------------------------------------

export interface MultiSearchQueryResult {
  query: string;
  status: "succeeded" | "failed" | "processing";
  error?: { code?: string; message: string; retryable?: boolean } | null;
  response?: Record<string, unknown> | null;
}

export interface MultiSearchResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  schema_version: string;
  search_id: string;
  queries_count: number;
  succeeded_count: number;
  failed_count: number;
  credits_used: number;
  results: MultiSearchQueryResult[];
}

export interface SearchRequest {
  /** Exactly one of `query` or `queries`. */
  query?: string;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  /** 1-5 queries run in one request and billed as one unit (returns MultiSearchResponse). */
  queries?: string[];
  engine?: "duckduckgo" | "google" | "bing" | "auto";
  domain?: string;
  num_results?: number;
  page?: number;
  country?: string;
  language?: string;
  time_range?: "hour" | "day" | "week" | "month" | "year";
  safe_search?: boolean;
  scrape_results?: boolean;
  /** With `scrape_results`, wait up to ~30s and return content in one call; on timeout the response is a 202 with `next_action`. */
  sync?: boolean;
  formats?: OutputFormat[];
  extraction_schema?: Record<string, unknown>;
  /** SERP layout to emulate (`/v1/serp` path only; ignored with scrape_results/domain/time_range). */
  device?: "desktop" | "mobile";
  /** Alias for `num_results`; takes precedence when both are set. */
  num?: number;
  /** 0-based offset of the first result (multiple of the result count); takes precedence over `page`. */
  start?: number;
  /** Google only: keep the search on the rendered tier so `ai_overview` carries the body. No extra charge. */
  include_ai_overview?: boolean;
  /** With `scrape_results`: seconds (1-60) to wait for result pages and return content inline (HTTP 200). Omit for the async flow. */
  wait?: number;
  /** Latency tier for inline content: fast (5 s), standard (15 s), deep (60 s); an explicit `wait` overrides it. */
  mode?: "fast" | "standard" | "deep";
  /** With `scrape_results`: false allows cached page content (default: fetch live). */
  live?: boolean;
  /** Agent preset for result content (markdown with size caps); set by the SDK when `concise` is on. */
  preset?: "agent";
  /** Unified search only: concise agent output for result content (default true). false returns full-length content. */
  concise?: boolean;
}

/** Outcome of fetching a result page (`scrape_results`). */
export type SearchContentStatus =
  | "ok"
  | "partial"
  | "blocked"
  | "timeout"
  | "dead_origin"
  | "pending";

/** A source cited by a Google AI Overview. */
export interface SearchAIOverviewReference {
  title: string;
  url: string;
  domain: string;
  /** 1-based position in page order. */
  position: number;
}

/** One headed (or leading, unheaded) block of AI Overview prose. */
export interface SearchAIOverviewSection {
  heading?: string | null;
  text: string;
}

/** Structured Google AI Overview. */
export interface SearchAIOverview {
  present: boolean;
  text: string;
  sections: SearchAIOverviewSection[];
  references: SearchAIOverviewReference[];
}

export interface SearchResult {
  url: string;
  title: string;
  snippet: string;
  position: number;
  date_published?: string;
  displayed_url?: string;
  sitelinks?: Array<{ title: string; url: string }>;
  content?: Record<string, unknown>;
  /** Result-page fetch outcome (`scrape_results` only). */
  content_status?: SearchContentStatus;
  /** ISO-8601 UTC time the result page was fetched. */
  fetched_at?: string | null;
  /** Rank-derived relevance in (0, 1]. */
  score?: number | null;
  /** Citation-ready metadata: url, title, published. */
  source?: Record<string, string> | null;
}

export interface SearchResponse {
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  /** Share of results with full content (`content_status` "ok"), 0-1; `scrape_results` only. */
  content_coverage?: number | null;
  search_id: string;
  query: string;
  results: SearchResult[];
  credits_used: number;
  cost_breakdown?: Record<string, unknown>;
  featured_snippet?: Record<string, unknown>;
  knowledge_panel?: Record<string, unknown>;
  people_also_ask?: Array<Record<string, unknown>>;
  related_searches?: string[];
  /** Present on a `sync: true` search that outlived its wait budget: a typed wait action naming the poll URL. */
  next_action?: Record<string, unknown>;
  /** Number of results requested by the caller (the `num_results` parameter). */
  results_requested: number;
  /** Number of results returned in this response. */
  results_count: number;
  /** Engine that actually served the results (`/v1/serp` surface). */
  engine_used?: string;
  /** True when the response was served from cache. */
  served_from_cache?: boolean;
  /**
   * Estimated total results available from the search engine. `null` when the engine
   * did not report a total.
   */
  estimated_total_results?: number | null;
  /** Search query correction suggestion (e.g. "Did you mean: ..."). */
  did_you_mean?: string | null;
  /** Paid text advertisements (top and bottom slots, if present). */
  ad_results?: SearchAdResult[];
  /** Local pack / Maps business listings (if present). */
  local_results?: SearchLocalResult[];
  /** Top stories / news carousel results (if present). */
  news_results?: SearchNewsResult[];
  /** Image carousel results (if present). */
  image_results?: SearchImageResult[];
  /** Video carousel results (if present). */
  video_results?: SearchVideoResult[];
  /** Shopping carousel results (if present). */
  shopping_results?: SearchShoppingResult[];
  /** Structured AI Overview (Google only); null when the serving engine had none. */
  ai_overview?: SearchAIOverview | null;
  /** Structured warnings indicating response degradation. Empty when fulfilled as requested. */
  warnings?: SearchWarning[];
}

/** A sitelink shown under a search result or ad. */
export interface SearchSitelink {
  title: string;
  url: string;
}

/** A paid text advertisement from a SERP (top or bottom slot). */
export interface SearchAdResult {
  /** 1-indexed position within the slot. */
  position: number;
  /** Ad slot: `"top"` or `"bottom"`. */
  slot: string;
  /** Ad headline text. */
  title?: string | null;
  /** URL as displayed in the ad (breadcrumb-style). */
  display_url?: string | null;
  /** Unwrapped destination URL of the ad. */
  destination_url?: string | null;
  /** Ad label text (e.g. "Sponsored"). */
  ad_label?: string | null;
  /** Ad identifier extracted from the SERP DOM. */
  ad_id?: string | null;
  /** Advertiser transparency URL. */
  advertiser_link?: string | null;
  /** Advertiser name. */
  advertiser_name?: string | null;
  /** Advertiser domain. */
  advertiser_domain?: string | null;
  /** Advertiser country from the ads transparency center. */
  advertiser_country?: string | null;
  /** Sitelink extensions shown under this ad. */
  sitelinks?: SearchSitelink[];
  /** Advertiser profile from the ads transparency center. */
  advertiser_profile?: Record<string, unknown> | null;
}

/** An image result from the image carousel. */
export interface SearchImageResult {
  /** Image URL or thumbnail URL. */
  image_url: string;
  alt_text?: string | null;
  /** Source page URL. */
  source_url?: string | null;
}

/** A local pack result (business listing). */
export interface SearchLocalResult {
  /** Business name. */
  name: string;
  address?: string | null;
  /** Star rating (1–5). */
  rating?: number | null;
  review_count?: number | null;
  phone?: string | null;
  category?: string | null;
}

/** A news result from the top stories / news carousel. */
export interface SearchNewsResult {
  /** News headline. */
  title: string;
  /** Article URL. */
  url: string;
  /** Publisher name. */
  source?: string | null;
  /** Publication date. */
  date?: string | null;
  thumbnail_url?: string | null;
}

/** A shopping result from the shopping carousel. */
export interface SearchShoppingResult {
  /** Product title. */
  title: string;
  /** Price string (e.g. `"$29.99"`). */
  price?: string | null;
  /** Merchant / seller name. */
  merchant?: string | null;
  image_url?: string | null;
  /** Product page URL. */
  link?: string | null;
  /** Star rating (1–5). */
  rating?: number | null;
  review_count?: number | null;
}

/** A video result shown in the video carousel. */
export interface SearchVideoResult {
  /** Video title. */
  title: string;
  /** Video URL. */
  url: string;
  /** Video platform (e.g. "YouTube"). */
  source?: string | null;
  /** Duration string. */
  duration?: string | null;
  thumbnail_url?: string | null;
  /** Upload/publish date. */
  date?: string | null;
}

/** A structured warning surfaced when a search response is degraded. */
export interface SearchWarning {
  /** Machine-readable warning code, e.g. `"scraping_skipped_insufficient_credits"`. */
  code: string;
  /** Human-readable explanation of the warning. */
  message: string;
}

/** Point and radius used to localize search results. */
export interface Coordinates {
  /** Latitude in decimal degrees (-90..90). */
  lat: number;
  /** Longitude in decimal degrees (-180..180). */
  lng: number;
  /** Localization radius in km (max 500; default 10). */
  radius_km?: number;
}

export interface BatchSearchRequest {
  queries: string[];
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  engine?: "duckduckgo" | "google" | "bing";
  num_results?: number;
  country?: string;
  language?: string;
  time_range?: "hour" | "day" | "week" | "month" | "year";
  safe_search?: boolean;
  scrape_results?: boolean;
  formats?: OutputFormat[];
  webhook_url?: string;
  /** Concise agent preset (when `scrape_results` is true): defaults formats to markdown and applies character caps. */
  preset?: "agent";
  /** Per-result character cap across text-like fields (1..1,000,000; when `scrape_results` is true). */
  max_chars_per_result?: number;
  /** Total character cap across all results, applied in rank order (1..5,000,000). */
  max_total_chars?: number;
  /** City to localize results to (e.g. `"London"`). Requires `country`. */
  city?: string | null;
  /** Point and radius to localize results to. */
  coordinates?: Coordinates | null;
  /** Device to emulate. Omit for the default layout. */
  device?: "desktop" | "mobile" | "tablet" | null;
  /** Skip the SERP cache and fetch fresh (billed at the full price). */
  no_cache?: boolean;
  /** Pre-encoded location (uule) for exact localization. Precedence: uule > coordinates > city > country. */
  uule?: string | null;
  /** Signing secret (16..256 chars); the webhook body then carries an `X-AlterLab-Signature` header. */
  webhook_secret?: string | null;
  /** Zero data retention: nothing about the query or its results is stored beyond the request. */
  zero_data_retention?: boolean | null;
  /** Zero data retention for this request: no caching and no persisted raw page or result row. */
  zero_trace?: boolean;
}

export interface BatchSearchResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  schema_version: string;
  batch_id: string;
  total_queries: number;
  status: string;
  estimated_credits: number;
  job_ids: string[];
  /** Submission confirmation; poll `GET /v1/search/batch/{batch_id}` for results. */
  message?: string;
}

/** Response from `GET /v1/search/{search_id}` (search started with `scrape_results`). */
export interface SearchStatusResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  schema_version: string;
  search_id: string;
  query: string;
  /** scraping | completed | partial | failed (late plain-search results: pending/completed/failed). */
  status: string;
  failure_reason?: string | null;
  results_requested: number;
  results_count: number;
  completed: number;
  failed?: number;
  credits_used?: number;
  /** Share of results with full content (`content_status` "ok"), 0-1. */
  content_coverage?: number | null;
  results?: SearchResult[];
  /** Per-call cost breakdown showing base search cost and per-page scrape costs. */
  cost_breakdown?: Record<string, unknown> | null;
  /** Paid text advertisements (top and bottom slots, if present). */
  ad_results?: SearchAdResult[];
  /** Paid ads above the organic results, if present. */
  ads_top?: SearchAdResult[];
  /** Paid ads below the organic results, if present. */
  ads_bottom?: SearchAdResult[];
  /** Paid Shopping ads (product listing ads), if present. */
  ads_shopping?: SearchAdResult[];
  [key: string]: unknown;
}

/** Response from `GET /v1/search/batch/{batch_id}`. */
export interface BatchSearchStatusResponse {
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  schema_version: string;
  batch_id: string;
  /** processing | completed | partial | failed */
  status: string;
  total: number;
  completed: number;
  failed: number;
  pending: number;
  items: Array<Record<string, unknown>>;
  total_credits_used: number;
  created_at: string;
  webhook_status?: string | null;
  webhook_attempts?: number;
}

// ---------------------------------------------------------------------------
// Map types
// ---------------------------------------------------------------------------

export interface MapRequest {
  url: string;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  max_pages?: number;
  max_depth?: number;
  include_patterns?: string[];
  exclude_patterns?: string[];
  search?: string;
  sitemap?: "skip" | "include" | "only";
  sitemap_path?: string;
  include_metadata?: boolean;
  include_subdomains?: boolean;
  respect_robots?: boolean;
}

export interface MapURLEntry {
  url: string;
  depth: number;
  source: "sitemap" | "link" | "start";
  title?: string;
  description?: string;
  relevance_score?: number;
}

export interface MapResponse {
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  map_id: string;
  total_urls: number;
  urls: MapURLEntry[];
  sitemap_found: boolean;
  robots_txt?: Record<string, unknown>;
  credits_used: number;
}

// ---------------------------------------------------------------------------
// Extract types
// ---------------------------------------------------------------------------

export interface ExtractRequest {
  content: string;
  /** Spend-attribution tag (^[a-z0-9][a-z0-9_.-]{0,63}$, max 20 active tags per organization); echoed in the response. */
  tag?: string | null;
  /** ID of a saved custom extraction template; its schema is used as `extraction_schema`. */
  extraction_template_id?: string | null;
  /** Pin a saved template version (>= 1); defaults to the current version. */
  extraction_template_version?: number | null;
  content_type?: "html" | "text" | "markdown";
  extraction_schema?: Record<string, unknown>;
  /** Deterministic field extraction evaluated on the fetched HTML; no LLM or BYOK key required. */
  extraction_selectors?: ExtractionSelectors;
  extraction_profile?:
    | "auto"
    | "product"
    | "article"
    | "job_posting"
    | "faq"
    | "recipe"
    | "event"
    | "ecommerce_homepage"
    | "directory_listing";
  extraction_prompt?: string;
  /**
   * LLM provider to use for extraction. Selects the matching BYOK key registered
   * at /dashboard/settings/llm-keys. When omitted, the most recently used
   * registered key is used automatically.
   */
  extraction_provider?: "openai" | "anthropic" | "openrouter" | "groq";
  /**
   * Per-request LLM model override in provider-specific format (e.g. `'gpt-4o'`,
   * `'claude-opus-4-5-20251101'`, `'llama3-70b-8192'`). When provided, overrides
   * the model saved in your BYOK key settings for this request only. When omitted,
   * the model configured on your registered key is used.
   */
  extraction_model?: string | null;
  /**
   * Shorthand for `extraction_profile`. Selects a pre-built schema template by name.
   * Mutually exclusive with `extraction_profile`.
   */
  extraction_template?:
    | "auto"
    | "product"
    | "article"
    | "job_posting"
    | "faq"
    | "recipe"
    | "event"
    | "ecommerce_homepage"
    | "directory_listing";
  formats?: OutputFormat[];
  source_url?: string;
  evidence?: boolean;
  /**
   * Cache control for LLM extraction results.
   * - `"auto"`: return cached result if available (default).
   * - `"skip"`: bypass cache, always call LLM (result still stored for future callers).
   * - `"only"`: return cached result or HTTP 404 — never calls the LLM.
   */
  cache?: "auto" | "skip" | "only";
  /**
   * TTL for caching this extraction result, in seconds (1–86400).
   * Defaults to the server-side LLM_EXTRACTION_CACHE_TTL env var (3600s).
   */
  cache_ttl?: number;
}

/**
 * Per-call extraction transparency metadata returned in POST /v1/extract responses.
 *
 * Provides full context about how the extraction was performed: which LLM provider
 * and model were used, token counts reported by the provider, AlterLab's invocation
 * fee, end-to-end latency, and whether a cached result was served.
 *
 * Token counts are `null` when no LLM was invoked (algorithmic extraction) or when
 * the provider did not report usage (some OpenRouter models omit usage fields).
 */
export interface ExtractionMetadata {
  /** Extraction mode: 'byok' when BYOK key was used, 'algorithmic' otherwise. */
  mode: string;
  /** LLM provider used (openai, anthropic, openrouter, groq), or null if no LLM ran. */
  provider?: string | null;
  /** LLM model ID used for extraction, or null if no LLM ran. */
  model?: string | null;
  /** Prompt token count reported by the provider, or null if unavailable. */
  input_tokens?: number | null;
  /** Completion token count reported by the provider, or null if unavailable. */
  output_tokens?: number | null;
  /** AlterLab invocation fee charged in microcents (net of any refunds). */
  cost_microcents: number;
  /** Whether a cached extraction result was served. */
  cached: boolean;
  /** End-to-end extraction latency in milliseconds. */
  latency_ms: number;
}

export interface ExtractResponse {
  /** Request tag echoed from the submitted request, if any. */
  tag?: string | null;
  /** Cost in USD as an exact decimal string (credits fields are microcents: 1 credit = $0.000001). */
  cost_usd?: string;
  extract_id: string;
  /**
   * Source citation to keep when presenting results. Present for free, trial and keyless
   * usage; omitted for paid accounts unless enabled in settings. Never alters the data.
   */
  attribution?: { text: string; url: string };
  formats: Record<string, unknown>;
  credits_used: number;
  model_used?: string;
  extraction_method: string;
  content_size_chars: number;
  /**
   * Extraction profile applied (if any): auto, product, article, job_posting,
   * faq, recipe, event, ecommerce_homepage, directory_listing.
   */
  extraction_profile?: string | null;
  /**
   * Full extraction context including provider, model, token usage,
   * invocation cost, latency, and cache status. Populated on every call.
   */
  extraction_metadata?: ExtractionMetadata | null;
  /**
   * True when the LLM extraction result was served from Redis cache.
   * When true, no LLM call was made and the BYOK invocation fee was not charged.
   */
  cache_hit: boolean;
}

export interface Logger {
  debug: (message: string, ...args: unknown[]) => void;
  warn: (message: string, ...args: unknown[]) => void;
  error: (message: string, ...args: unknown[]) => void;
}

// ---------------------------------------------------------------------------
// Extraction estimate, usage, and template types
// ---------------------------------------------------------------------------

/** Cost breakdown for GET /v1/extract/estimate. */
export interface ExtractionEstimateBreakdown {
  /** Content transformation cost (ContentTransformer pipeline) in microcents. */
  base_cost_microcents: number;
  /** LLM invocation fee in microcents (0 when has_extraction_prompt is false). */
  llm_cost_microcents: number;
  /** Minimum charge enforced per extraction call in microcents. */
  min_charge_microcents: number;
  /** Maximum charge cap per extraction call in microcents. */
  max_charge_microcents: number;
}

/** Response from GET /v1/extract/estimate. */
export interface ExtractionEstimateResponse {
  /** Estimated total cost in microcents. Clamped to [100, 50000] µ¢. */
  estimated_cost_microcents: number;
  /** Estimated cost formatted as USD string (e.g. '$0.0025'). */
  estimated_cost_usd: string;
  /** Per-component cost breakdown. */
  breakdown: ExtractionEstimateBreakdown;
}

/** Single row from the extraction_usage table. */
export interface ExtractionUsageRecord {
  /** Unique extraction usage record ID (UUID). */
  id: string;
  /** Timestamp of the extraction call (UTC). */
  created_at: string;
  /** Extraction mode: 'byok' for Bring Your Own Key, 'platform' for managed. */
  extraction_mode: string;
  /** LLM provider used (openai, anthropic, openrouter, groq), or null. */
  provider?: string | null;
  /** LLM model ID used, or null when no LLM ran. */
  model?: string | null;
  /** Prompt token count reported by the provider. */
  input_tokens?: number | null;
  /** Completion token count reported by the provider. */
  output_tokens?: number | null;
  /** AlterLab invocation fee charged for this call (microcents). */
  billed_cost_microcents: number;
  /** End-to-end extraction latency in milliseconds. */
  latency_ms: number;
  /** Target domain if triggered via /v1/scrape, otherwise null. */
  domain?: string | null;
  /** True when extraction_schema was provided (structured extraction). */
  has_schema: boolean;
  /** True when extraction produced a parseable result. */
  success: boolean;
  /** Error classification if not successful. */
  error_type?: string | null;
}

/** Paginated list of extraction usage records. */
export interface ExtractionUsageListResponse {
  /** Extraction usage records for the requested page. */
  items: ExtractionUsageRecord[];
  /** Total number of records matching the filter. */
  total: number;
  /** Current page (1-indexed). */
  page: number;
  /** Number of records per page. */
  page_size: number;
  /** True when additional pages are available. */
  has_more: boolean;
}

/** Aggregate extraction usage totals for a time period. */
export interface ExtractionUsageSummaryResponse {
  /** Total number of extraction invocations in the period. */
  total_requests: number;
  /** Sum of billed_cost_microcents for all extraction invocations in the period. */
  total_cost_microcents: number;
}

// ---------------------------------------------------------------------------
// Scrape template types (public, no auth required)
// ---------------------------------------------------------------------------

/** Options for listing scrape templates. */
export interface ScrapeTemplateListOptions {
  /** Page number (1-based, default 1). */
  page?: number;
  /** Items per page (1–100, default 20). */
  page_size?: number;
  /** Filter templates by tag. */
  tag?: string;
}

/** A single scrape template item. */
export interface ScrapeTemplateItem {
  /** Template UUID. */
  id: string;
  /** URL-safe unique identifier. */
  slug: string;
  /** Human-readable template name. */
  name: string;
  /** What this template does. */
  description: string;
  /** URL glob pattern this template targets (e.g. `amazon.com/dp/*`). */
  url_pattern: string;
  /** Subset of scrape request fields (minus url). */
  request_config: Record<string, unknown>;
  /** Categorisation tags. */
  tags: string[];
  /** Number of times this template has been used. */
  use_count: number;
  /** Whether this template is maintained by the AlterLab team. */
  created_by_team: boolean;
  /** When the template was created. */
  created_at: string;
  /** When the template was last updated. */
  updated_at: string;
}

/** Paginated response for listing scrape templates. */
export interface ScrapeTemplateListResponse {
  /** List of templates on this page. */
  templates: ScrapeTemplateItem[];
  /** Total number of matching templates. */
  total: number;
  /** Current page number (1-based). */
  page: number;
  /** Number of templates per page. */
  page_size: number;
}

/** Response for getting a single scrape template by slug. */
export interface ScrapeTemplateDetailResponse extends ScrapeTemplateItem {}

// ---------------------------------------------------------------------------
// Session types
// ---------------------------------------------------------------------------

export interface SessionIntegration {
  id: string;
  name: string;
  domain: string;
  /** Cookie names only — values are never exposed in API responses. */
  cookie_names: string[];
  header_names?: string[] | null;
  status: "active" | "expired" | "invalid" | "pending_validation";
  expires_at?: string | null;
  last_validated_at?: string | null;
  validation_confidence?: number | null;
  consecutive_failures: number;
  last_used_at?: string | null;
  total_requests: number;
  successful_requests: number;
  success_rate: number;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: SessionIntegration[];
  total: number;
}

export interface SessionValidation {
  is_valid: boolean;
  confidence: number;
  http_status?: number | null;
  detected_user?: string | null;
  cookie_expiry_detected?: string | null;
  cookies_expiring_soon: boolean;
  indicators_found?: Record<string, string[]> | null;
  consecutive_failures: number;
  details: string;
}

export interface SessionCreateRequest {
  name: string;
  domain: string;
  /** Cookie data for server-side encryption. Either a `{name: value}` map or a cookie string. */
  cookies: Record<string, string>;
  headers?: Record<string, string>;
  expires_at?: string;
  notes?: string;
  /**
   * Encryption mode: `"server"` (default, AlterLab encrypts) or `"client"` (zero-knowledge,
   * you encrypt the cookies client-side and pass the ciphertext via `encrypted_cookies`).
   */
  encryption_mode?: "server" | "client";
  /**
   * Client-encrypted cookie blob: `base64(iv).base64(ciphertext)`.
   * Use with `encryption_mode: "client"` and `wrapped_key`.
   */
  encrypted_cookies?: string;
  /**
   * RSA-OAEP wrapped AES-256 session key (base64).
   * Required when `encryption_mode: "client"`.
   */
  wrapped_key?: string;
  /** RSA key version used for encryption. */
  key_version?: string;
  /**
   * Plaintext cookie names for UI display (no cookie values are stored here).
   * Useful when using `encryption_mode: "client"` where the server cannot inspect values.
   */
  cookie_names?: string[];
  /** Share this session with all members of the assigned organization immediately. */
  shared?: boolean;
  /** Organization ID to assign this session to (org admin permission required). */
  organization_id?: string;
  /** Send a notification when the session is about to expire. */
  notify_before_expiry?: boolean;
  /** Send a notification when session validation fails. */
  notify_on_failure?: boolean;
  /** Enable proactive expiry detection and health checks. */
  auto_refresh_enabled?: boolean;
  /** Explicit GDPR consent to process session cookie data. */
  consent?: boolean;
  /** Extra domains this session may serve (same registered domain or SSO group). Max 10. */
  domain_set?: string[];
  /**
   * Browser storage: `{origins: [{origin, localStorage: [{name, value}], sessionStorage: [...]}]}`.
   * Sealed at rest, never returned.
   */
  storage_state?: Record<string, unknown>;
  /** Allowed use: `"read"` (default) and/or `"write"`. */
  scopes?: Array<"read" | "write">;
  /** Pinned identity profile (UUID). */
  identity_profile_id?: string;
  /** How the session was captured. */
  connected_via?: "extension" | "remote_browser" | "manual";
  /**
   * Capture-time `{user_agent, platform, locale, timezone}`; pins the session's
   * fingerprint and exit for every run.
   */
  capture_context?: Record<string, unknown>;
}

export interface SessionUpdateRequest {
  name?: string;
  cookies?: Record<string, string>;
  headers?: Record<string, string>;
  expires_at?: string;
  notes?: string;
  /** Enable/disable proactive expiry detection. */
  auto_refresh_enabled?: boolean;
  /** Enable/disable pre-expiry notifications. */
  notify_before_expiry?: boolean;
  /** Enable/disable failure notifications. */
  notify_on_failure?: boolean;
  /** Extra domains this session may serve (same registered domain or SSO group). Max 10. */
  domain_set?: string[];
  /**
   * Browser storage: `{origins: [{origin, localStorage: [{name, value}], sessionStorage: [...]}]}`.
   * Sealed at rest, never returned.
   */
  storage_state?: Record<string, unknown>;
  /** Allowed use: `"read"` (default) and/or `"write"`. */
  scopes?: Array<"read" | "write">;
  /** Pinned identity profile (UUID). */
  identity_profile_id?: string;
  /** How the session was captured. */
  connected_via?: "extension" | "remote_browser" | "manual";
  /**
   * Capture-time `{user_agent, platform, locale, timezone}`; pins the session's
   * fingerprint and exit for every run.
   */
  capture_context?: Record<string, unknown>;
}

/**
 * Body of `POST /api/v1/sessions/{id}/refresh`. Pass `cookies` for server-side
 * encryption, or `encryption_mode: "client"` with the output of
 * `encryptCookies()` (`encrypted_cookies`, `wrapped_key`, `cookie_names`).
 */
export interface SessionRefreshRequest {
  cookies?: Record<string, string>;
  headers?: Record<string, string>;
  encryption_mode?: "server" | "client";
  /** Client-encrypted cookie blob: `base64(iv).base64(ciphertext)`. */
  encrypted_cookies?: string;
  /** RSA-OAEP wrapped AES-256 session key (base64). */
  wrapped_key?: string;
  /** Plaintext cookie names for UI display (no values). */
  cookie_names?: string[];
  /** RSA key version used for encryption. */
  key_version?: number;
}

export interface SessionListOptions {
  domain?: string;
  status?: string;
  /** Include organization-shared sessions from teams you belong to. */
  include_shared?: boolean;
}

// ---------------------------------------------------------------------------
// Loggers
// ---------------------------------------------------------------------------

/** Default console logger */
const defaultLogger: Logger = {
  debug: (msg, ...args) => console.debug(`[alterlab] ${msg}`, ...args),
  warn: (msg, ...args) => console.warn(`[alterlab] ${msg}`, ...args),
  error: (msg, ...args) => console.error(`[alterlab] ${msg}`, ...args),
};

/** No-op logger for silent operation */
export const silentLogger: Logger = {
  debug: () => {},
  warn: () => {},
  error: () => {},
};

// ---------------------------------------------------------------------------
// Error classes
// ---------------------------------------------------------------------------

/**
 * Thrown when a job has expired (TTL: 1 hour) and the API returns HTTP 404.
 *
 * Callers should catch this to distinguish between "job expired" and other
 * failure modes. Do not retry with the same job ID — the result is gone.
 * Create a new job with `client.scrape({ sync: false })`.
 *
 * ```ts
 * try {
 *   const result = await client.waitForJob(jobId);
 * } catch (e) {
 *   if (e instanceof JobExpiredError) {
 *     console.error(`Job ${e.jobId} expired. Submit a new request.`);
 *   }
 * }
 * ```
 */
export class JobExpiredError extends Error {
  /** Stable error code (#40335). */
  readonly code: string = "job_expired";
  readonly retryable: boolean = false;
  readonly retryAfterSeconds: number | null = null;
  readonly nextAction: Record<string, unknown> | null = null;
  readonly requestId: string | null = null;
  /** The job ID that was not found (expired). */
  readonly jobId: string;

  constructor(jobId: string) {
    super(
      `Job ${jobId} has expired (TTL: 1 hour). Create a new job with client.scrape().`,
    );
    this.name = "JobExpiredError";
    this.jobId = jobId;
    // Maintain proper stack trace in V8 environments (Node.js / Chrome)
    const ErrorWithCapture = Error as typeof Error & {
      captureStackTrace?: (target: object, constructor: Function) => void;
    };
    if (ErrorWithCapture.captureStackTrace) {
      ErrorWithCapture.captureStackTrace(this, JobExpiredError);
    }
  }
}

/**
 * Thrown by `waitForJob()` (and so `scrape()`) when the SDK poll timeout
 * elapses before the job finishes. The job may still be running server-side
 * and credits may still be held: resume with `getJobStatus(e.jobId)` or
 * `e.pollUrl`. Extends `Error`, so existing `catch` blocks keep working.
 */
export class JobTimeoutError extends Error {
  /** Stable error code (#40335). */
  readonly code: string = "job_timeout";
  readonly retryable: boolean = false;
  readonly retryAfterSeconds: number | null = null;
  readonly nextAction: Record<string, unknown> | null = null;
  readonly requestId: string | null = null;
  readonly jobId: string;
  readonly pollUrl: string;

  constructor(jobId: string, timeoutSeconds: number) {
    super(`Job ${jobId} did not complete within ${timeoutSeconds} seconds`);
    this.name = "JobTimeoutError";
    this.jobId = jobId;
    this.pollUrl = `/api/v1/jobs/${jobId}`;
    Object.setPrototypeOf(this, JobTimeoutError.prototype);
  }
}

/**
 * Retry guidance the API attaches to some failed jobs as `error.hint`.
 *
 * Present when a request forced browser rendering (`render_js: true` or
 * `cost_controls.force_tier: "4"`) and the page returned a verification screen
 * or did not finish loading in time. `code` is `"render_js_auto"`: retrying
 * with `render_js: "auto"` lets the platform start at the lowest tier that
 * returns the page.
 */
export interface ForcedRenderHint {
  code: string;
  /** `"challenge"` or `"timeout"`. */
  reason: string;
  message: string;
}

function coerceHint(value: unknown): ForcedRenderHint | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const obj = value as Record<string, unknown>;
  if (typeof obj.code !== "string" || typeof obj.message !== "string") {
    return null;
  }
  return {
    code: obj.code,
    reason: typeof obj.reason === "string" ? obj.reason : "",
    message: obj.message,
  };
}

function errorObjectHint(error: unknown): ForcedRenderHint | null {
  if (!error || typeof error !== "object" || Array.isArray(error)) return null;
  return coerceHint((error as Record<string, unknown>).hint);
}

/**
 * Return the retry hint carried by a failed request, job or crawl page.
 *
 * Accepts a `JobFailedError`, the `AxiosError` thrown for a failed sync scrape
 * (HTTP 422 body `{detail, error: {..., hint}}`), or a raw error object such
 * as a crawl page's `error`. Returns `null` when there is no well-formed hint.
 *
 * ```ts
 * try {
 *   await client.scrape({ url, advanced: { render_js: true } });
 * } catch (e) {
 *   const hint = getErrorHint(e);
 *   if (hint) console.log(hint.message);
 * }
 * ```
 */
export function getErrorHint(error: unknown): ForcedRenderHint | null {
  if (error instanceof JobFailedError) return error.hint;
  if (error instanceof RateLimitError) return error.hint;
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (data && typeof data === "object") {
      return (
        errorObjectHint((data as Record<string, unknown>).error) ??
        coerceHint(detailHintSource(data))
      );
    }
    return null;
  }
  return errorObjectHint(error);
}

/**
 * Thrown when a polled job reaches a terminal failure state.
 *
 * Covers the server's `failed`, `rejected`, and `cancelled` terminal
 * statuses (see `JobStatus` in `services/api/app/models/job.py`) — all
 * three mean the job will never produce a result, distinct from a poll
 * timeout (job may still be running) or job expiry (result TTL elapsed).
 */
export class JobFailedError extends Error {
  /**
   * Stable error code (#40335): the job's `error.error_code` when the API
   * sent one, otherwise `"job_failed"`.
   */
  readonly code: string;
  /** The job's `error.error_code`, or `null` when absent (#41159). */
  readonly errorCode: string | null;
  readonly retryable: boolean;
  readonly retryAfterSeconds: number | null;
  /** Whether the failed job was charged, or `null` when the API did not say. */
  readonly charged: boolean | null;
  /** The API's auto-retry disposition (e.g. `"none"`), or `null`. */
  readonly autoRetry: string | null;
  readonly nextAction: Record<string, unknown> | null;
  readonly requestId: string | null = null;
  readonly jobId: string;
  readonly status: JobStatus;
  /** Retry guidance from the job's `error.hint`, or `null` when absent. */
  readonly hint: ForcedRenderHint | null;

  /**
   * @param envelope The failed job's `error` value and `next_action`; the
   *   failure envelope fields (#40689) are read from them.
   */
  constructor(
    jobId: string,
    status: JobStatus,
    detail: string,
    hint: ForcedRenderHint | null = null,
    envelope: {
      error?: unknown;
      next_action?: unknown;
    } = {},
  ) {
    super(`Job ${jobId} ended with status '${status}': ${detail}`);
    const err: Record<string, unknown> =
      envelope.error && typeof envelope.error === "object"
        ? (envelope.error as Record<string, unknown>)
        : {};
    const asRecord = (v: unknown): Record<string, unknown> | null =>
      v && typeof v === "object" && !Array.isArray(v)
        ? (v as Record<string, unknown>)
        : null;
    const nextAction =
      asRecord(err.next_action) ?? asRecord(envelope.next_action);
    const pick = (key: string): unknown =>
      err[key] !== undefined ? err[key] : nextAction?.[key];
    const errorCode = pick("error_code");
    const retryAfter = pick("retry_after_s");
    const autoRetry = pick("auto_retry");
    this.errorCode =
      typeof errorCode === "string" && errorCode ? errorCode : null;
    this.code = this.errorCode ?? "job_failed";
    this.retryable = pick("retryable") === true;
    this.retryAfterSeconds = typeof retryAfter === "number" ? retryAfter : null;
    this.charged =
      typeof pick("charged") === "boolean"
        ? (pick("charged") as boolean)
        : null;
    this.autoRetry = typeof autoRetry === "string" ? autoRetry : null;
    this.nextAction = nextAction;
    this.name = "JobFailedError";
    this.jobId = jobId;
    this.status = status;
    this.hint = hint;
    const ErrorWithCapture = Error as typeof Error & {
      captureStackTrace?: (target: object, constructor: Function) => void;
    };
    if (ErrorWithCapture.captureStackTrace) {
      ErrorWithCapture.captureStackTrace(this, JobFailedError);
    }
  }
}

/**
 * Thrown when the API returns HTTP 429 and the SDK stops retrying — all
 * attempts exhausted, or the next `Retry-After` would exceed `maxRetryWait`.
 *
 * Extends `AxiosError`, so existing `axios.isAxiosError(e)` /
 * `e.response?.status` handling keeps working. The fields of the canonical
 * 429 body (`{error, message, detail: {scope, limit, account_tier,
 * retry_after_seconds}, docs_url}`) and the `RateLimit-*` headers are
 * surfaced as properties; they are `null` for a 429 without that body, e.g.
 * one served by the edge (`error code: 1015`) rather than the API.
 *
 * `consecutiveFailures`, `outcomeClass` and `failureCode` are set only for the
 * repeat-failure back-off 429 (`errorCode === "repeat_failure_backoff"`): an
 * uncharged 429 returned when the same request failed the same way several
 * times in a row. Its retry guidance is in `hint` (also returned by
 * `getErrorHint(e)`): retry after `retryAfter`, retry with different request
 * options, or pass `forceRefresh: true`.
 *
 * ```ts
 * try {
 *   await client.scrape({ url: "https://example.com" });
 * } catch (e) {
 *   if (e instanceof RateLimitError && e.retryAfter !== null) {
 *     console.warn(`Rate limited (${e.scope}); retry in ${e.retryAfter}s`);
 *   }
 * }
 * ```
 */
export class RateLimitError extends AxiosError {
  /** Seconds the server asked to wait (header, else body), or null. */
  readonly retryAfter: number | null;
  readonly errorCode: string | null;
  readonly scope: string | null;
  readonly limit: number | null;
  readonly accountTier: string | null;
  readonly docsUrl: string | null;
  readonly rateLimitLimit: string | null;
  readonly rateLimitRemaining: string | null;
  readonly rateLimitReset: string | null;
  /** Consecutive identical failures (repeat-failure back-off 429 only). */
  readonly consecutiveFailures: number | null;
  /** Class of the repeated failure, e.g. `"challenge"` (back-off 429 only). */
  readonly outcomeClass: string | null;
  /** Error code of the repeated failure (back-off 429 only). */
  readonly failureCode: string | null;
  /** Retry guidance from `error.hint` or `detail.hint`, or null when absent. */
  readonly hint: ForcedRenderHint | null;
  /** `false` when retrying cannot succeed before `retryAt` (spend limit); null when absent. */
  readonly retryable: boolean | null;
  /** Earliest useful retry time (ISO-8601) for a terminal 429, or null. */
  readonly retryAt: string | null;

  /** True for `spend_limit_exceeded` or `detail.retryable === false`: never sleep or retry. */
  get terminal(): boolean {
    return (
      this.errorCode === "spend_limit_exceeded" || this.retryable === false
    );
  }

  constructor(source: AxiosError) {
    const response = source.response;
    const headers = (response?.headers ?? {}) as Record<string, unknown>;
    const header = (name: string): string | null => {
      const v = headers[name];
      return typeof v === "string" || typeof v === "number" ? String(v) : null;
    };
    const body = response?.data;
    const obj =
      body && typeof body === "object" && !Array.isArray(body)
        ? (body as Record<string, unknown>)
        : null;
    const detail =
      obj && obj.detail && typeof obj.detail === "object"
        ? (obj.detail as Record<string, unknown>)
        : null;
    const str = (v: unknown): string | null =>
      typeof v === "string" ? v : null;

    const bodyMessage = str(obj?.message);
    super(
      bodyMessage ?? source.message,
      source.code,
      source.config,
      source.request,
      response,
    );
    this.name = "RateLimitError";
    this.cause = source;

    const headerRetryMs = parseRetryAfterMs(headers["retry-after"]);
    const bodyRetry = detail?.retry_after_seconds;
    this.retryAfter =
      headerRetryMs !== null
        ? headerRetryMs / 1000
        : typeof bodyRetry === "number" && Number.isFinite(bodyRetry)
          ? bodyRetry
          : null;
    this.errorCode = str(obj?.error);
    this.retryable =
      typeof detail?.retryable === "boolean" ? detail.retryable : null;
    this.retryAt = str(detail?.retry_at);
    this.scope = str(detail?.scope) ?? header("x-ratelimit-scope");
    this.limit = typeof detail?.limit === "number" ? detail.limit : null;
    this.accountTier = str(detail?.account_tier);
    this.docsUrl = str(obj?.docs_url);
    this.rateLimitLimit =
      header("ratelimit-limit") ?? header("x-ratelimit-limit");
    this.rateLimitRemaining = header("ratelimit-remaining");
    this.rateLimitReset = header("ratelimit-reset");
    const backoff = parseFailureBackoffDetail(detail);
    this.consecutiveFailures = backoff.consecutiveFailures;
    this.outcomeClass = backoff.outcomeClass;
    this.failureCode = backoff.failureCode;
    this.hint = errorObjectHint(obj?.error) ?? coerceHint(detail?.hint);
  }
}

/**
 * Thrown for HTTP 402 (insufficient balance). Extends `AxiosError`, so existing
 * `axios.isAxiosError` / status checks keep working.
 *
 * `topupUrl` is a signed, short-lived link to the quick top-up confirm banner
 * (it never charges). `welcomeOffer` is set while the account's welcome offer
 * is active. Both are `null` when the server did not send them.
 *
 * ```ts
 * try {
 *   await client.scrape("https://example.com");
 * } catch (e) {
 *   if (e instanceof InsufficientFundsError) console.log(e.topupUrl ?? e.billingUrl);
 * }
 * ```
 */
export class InsufficientFundsError extends AxiosError {
  readonly billingUrl = "https://alterlab.io/dashboard/billing";
  readonly topupUrl: string | null;
  readonly welcomeOffer: { expires_at: string; match_pct: number } | null;

  constructor(source: AxiosError) {
    super(
      source.message,
      source.code,
      source.config,
      source.request,
      source.response,
    );
    this.name = "InsufficientFundsError";
    this.cause = source;

    const body = source.response?.data;
    const isObj = (v: unknown): v is Record<string, unknown> =>
      !!v && typeof v === "object" && !Array.isArray(v);
    // The fields sit under `detail` (API), top level (Firecrawl-compat) or
    // under `error` (sync scrape rejection) depending on the route.
    const layers: Record<string, unknown>[] = [];
    if (isObj(body)) {
      layers.push(body);
      if (isObj(body.detail)) layers.push(body.detail);
      if (isObj(body.error)) layers.push(body.error);
    }
    let topupUrl: string | null = null;
    let welcomeOffer: InsufficientFundsError["welcomeOffer"] = null;
    for (const layer of layers) {
      if (topupUrl === null && typeof layer.topup_url === "string") {
        topupUrl = layer.topup_url;
      }
      if (welcomeOffer === null && isObj(layer.welcome_offer)) {
        welcomeOffer =
          layer.welcome_offer as InsufficientFundsError["welcomeOffer"];
      }
    }
    this.topupUrl = topupUrl;
    this.welcomeOffer = welcomeOffer;
  }
}

// ---------------------------------------------------------------------------
// Sessions resource
// ---------------------------------------------------------------------------

/**
 * Session management resource.
 *
 * Access via `client.sessions`.
 *
 * ```ts
 * const session = await client.sessions.create({
 *   name: 'My Amazon Prime',
 *   domain: 'amazon.com',
 *   cookies: { 'session-id': 'abc123' },
 * });
 * const sessions = await client.sessions.list();
 * const validation = await client.sessions.validate(session.id);
 * await client.sessions.delete(session.id);
 * ```
 */
export class Sessions {
  constructor(
    private requestWithRetry: <T>(config: AxiosRequestConfig) => Promise<T>,
  ) {}

  /** Create a new session integration with encrypted cookie storage. */
  async create(request: SessionCreateRequest): Promise<SessionIntegration> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/sessions",
      data: request,
    });
  }

  /** List all session integrations for the authenticated user. */
  async list(options?: SessionListOptions): Promise<SessionListResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/sessions",
      params: options,
    });
  }

  /** Get a single session integration by ID. */
  async get(sessionId: string): Promise<SessionIntegration> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}`,
    });
  }

  /** Update a session integration. Only provided fields are changed. */
  async update(
    sessionId: string,
    request: SessionUpdateRequest,
  ): Promise<SessionIntegration> {
    return this.requestWithRetry({
      method: "PATCH",
      url: `/api/v1/sessions/${sessionId}`,
      data: request,
    });
  }

  /** Delete a session integration (soft delete). */
  async delete(sessionId: string): Promise<void> {
    await this.requestWithRetry<void>({
      method: "DELETE",
      url: `/api/v1/sessions/${sessionId}`,
    });
  }

  /**
   * Validate a session by testing its cookies against the target domain.
   * Makes a real HTTP request and checks for logged-in indicators.
   */
  async validate(sessionId: string): Promise<SessionValidation> {
    return this.requestWithRetry({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/validate`,
    });
  }

  /**
   * Refresh (rotate) session cookies. Replaces all cookies, resets failure
   * counters, and sets status back to active.
   */
  async refresh(
    sessionId: string,
    request: SessionRefreshRequest,
  ): Promise<SessionIntegration> {
    return this.requestWithRetry({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/refresh`,
      data: request,
    });
  }
}

// ---------------------------------------------------------------------------
// Main client
// ---------------------------------------------------------------------------

export class AlterLab {
  private client: AxiosInstance;
  private baseUrl: string;
  private apiKey: string;
  private maxRetries: number;
  private retryDelay: number;
  private maxRetryWait: number | null;
  private logger: Logger;

  /** Session management — create, list, get, update, delete, validate, refresh. */
  public readonly sessions: Sessions;
  /** Wallet balance and usage. */
  public readonly account: AccountNamespace;
  /** Support tickets (`support.ticket`). */
  public readonly support: SupportNamespace;
  /** Job reports (`jobs.report`) and explanations. */
  public readonly jobs: JobsNamespace;
  public readonly monitors: MonitorsNamespace;
  public readonly schedules: SchedulesNamespace;
  public readonly store: StoreNamespace;
  public readonly feeds: FeedsNamespace;
  public readonly workflows: WorkflowsNamespace;
  private parity: McpParity;

  constructor(options: AlterLabOptions) {
    this.baseUrl = options.baseUrl || "https://api.alterlab.io";
    this.apiKey = options.apiKey;
    this.maxRetries = options.maxRetries ?? 3;
    this.retryDelay = options.retryDelay ?? 1000;
    this.maxRetryWait =
      options.maxRetryWait === undefined
        ? DEFAULT_MAX_RETRY_WAIT_MS
        : options.maxRetryWait;
    if (this.maxRetryWait !== null && !(this.maxRetryWait >= 0)) {
      throw new Error("maxRetryWait must be >= 0 or null");
    }
    this.logger = options.logger ?? defaultLogger;

    this.client = axios.create({
      baseURL: this.baseUrl,
      headers: {
        "X-API-Key": options.apiKey,
        "Content-Type": "application/json",
        "User-Agent": `AlterLab-Node-SDK/${SDK_VERSION}`,
        "X-AlterLab-Source": `node-sdk/${SDK_VERSION}`,
      },
    });

    // Bind requestWithRetry so Sessions can use it
    this.sessions = new Sessions(this.requestWithRetry.bind(this));
    const parity = createParity(
      this.requestWithRetry.bind(this),
      () => options.onUnexpectedResponse,
    );
    this.parity = parity.parity;
    this.account = parity.account;
    this.support = parity.support;
    this.jobs = parity.jobs;
    this.monitors = parity.monitors;
    this.schedules = parity.schedules;
    this.store = parity.store;
    this.feeds = parity.feeds;
    this.workflows = parity.workflows;
  }

  private async requestWithRetry<T>(config: AxiosRequestConfig): Promise<T> {
    const response = await this.requestWithRetryRaw<T>(config);
    return response.data;
  }

  /**
   * Same retry/backoff behavior as {@link requestWithRetry}, but returns the
   * full axios response (status + headers) instead of just `.data`.
   *
   * Needed by {@link scrape} to detect a `202` sync-downgrade response —
   * axios's default `validateStatus` treats any 2xx as success, so a plain
   * `.data` return would silently hand a `{job_id, sync_downgraded: true}`
   * envelope back to the caller typed as a completed `ScrapeResponse`
   * (#31823).
   */
  private async requestWithRetryRaw<T>(
    config: AxiosRequestConfig,
  ): Promise<AxiosResponse<T>> {
    let lastError: Error | null = null;
    let waited = 0;

    for (let attempt = 0; attempt < this.maxRetries; attempt++) {
      try {
        return await this.client.request<T>(config);
      } catch (error) {
        const axiosError = error as AxiosError;
        const status = axiosError.response?.status;
        const isRetriable = status && RETRIABLE_STATUS_CODES.has(status);
        const isNetworkError =
          !axiosError.response && axiosError.code !== "ERR_CANCELED";

        if (!isRetriable && !isNetworkError) {
          // Non-retriable error (4xx except 429)
          this.logger.debug(
            `Non-retriable error ${status} on ${config.method} ${config.url}: ${axiosError.message}`,
          );
          if (status === 402) {
            const funds = new InsufficientFundsError(axiosError);
            applyTypedFields(funds, axiosError);
            throw funds;
          }
          throw toTypedError(error);
        }

        let retryAfterMs = parseRetryAfterMs(
          axiosError.response?.headers?.["retry-after"],
        );
        if (status === 429) {
          const rateLimitError = new RateLimitError(axiosError);
          lastError = rateLimitError;
          if (rateLimitError.terminal) break;
          if (rateLimitError.retryAfter !== null) {
            retryAfterMs = rateLimitError.retryAfter * 1000;
          }
        } else {
          lastError = axiosError;
        }
        const remainingAttempts = this.maxRetries - attempt - 1;
        if (remainingAttempts <= 0) break;

        const sleepTime = Math.round(
          computeRetrySleepMs(attempt, this.retryDelay, retryAfterMs),
        );
        const errorType = isNetworkError ? "Network error" : `HTTP ${status}`;

        if (
          this.maxRetryWait !== null &&
          waited + sleepTime > this.maxRetryWait
        ) {
          this.logger.warn(
            `${errorType} on ${config.method} ${config.url}: next retry in ${sleepTime}ms ` +
              `would exceed maxRetryWait=${this.maxRetryWait}ms (already waited ${waited}ms). Not retrying.`,
          );
          break;
        }

        this.logger.warn(
          `${errorType} on ${config.method} ${config.url} (attempt ${attempt + 1}/${this.maxRetries}). ` +
            `Retrying in ${sleepTime}ms. ${remainingAttempts} attempts remaining.`,
        );
        waited += sleepTime;
        await this.sleep(sleepTime);
      }
    }

    this.logger.error(
      `Giving up on ${config.method} ${config.url} after ${waited}ms of retry waits (maxRetries=${this.maxRetries})`,
    );
    // A 429 stays a RateLimitError: it carries terminal / retryAt / back-off fields (#40324,
    // #36240) that the generated typed classes for spend_limit_exceeded and
    // repeat_failure_backoff do not.
    if (lastError instanceof RateLimitError) {
      applyTypedFields(lastError, lastError);
      throw lastError;
    }
    throw toTypedError(lastError) || new Error("Request failed after retries");
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Scrape a URL. Supports inline cookies and stored session references
   * for authenticated scraping.
   *
   * ```ts
   * // One-off cookies
   * const result = await client.scrape({
   *   url: 'https://amazon.com/dp/B0XXXXX',
   *   cookies: { 'session-id': 'abc123' },
   * });
   *
   * // Stored session
   * const result = await client.scrape({
   *   url: 'https://amazon.com/dp/B0XXXXX',
   *   sessionId: 'uuid-of-stored-session',
   * });
   * ```
   */
  scrape(
    request: ScrapeRequest & { sync: false },
  ): Promise<ScrapeAcceptedResponse>;
  scrape(request: ScrapeRequest): Promise<ScrapeResponse>;
  async scrape(
    request: ScrapeRequest,
  ): Promise<ScrapeResponse | ScrapeAcceptedResponse> {
    if (
      request.sync === false &&
      request.sync_policy === "wait_until_deadline"
    ) {
      throw new Error(
        "sync_policy='wait_until_deadline' requires sync=true; " +
          "use sync_policy='auto' when sync=false.",
      );
    }

    if (request.sessionId && request.cookies) {
      throw new Error(
        "Cannot provide both sessionId and cookies. " +
          "Use sessionId to reference a stored session OR provide inline cookies, not both.",
      );
    }

    // Build the payload, mapping camelCase SDK params to snake_case API params
    const {
      sessionId,
      cookies,
      scroll_to_load,
      scroll_count,
      section_filter,
      include_iframes,
      flatten_shadow_dom,
      block_images,
      actions,
      actions_on_error,
      session_headers,
      use_own_proxy,
      use_system_proxy,
      proxy_integration_id,
      proxy_country,
      sticky_session,
      sticky_session_ttl,
      skip_tls_verification,
      remove_cookie_banners,
      headers,
      agentIntent,
      agentContext,
      agentFeedback,
      paymentSignature,
      template,
      ...rest
    } = request;
    const data: Record<string, unknown> = { ...rest };

    // Custom request headers are a top-level API field (not inside advanced)
    if (headers !== undefined) {
      data.headers = headers;
    }

    // Opt-in agent-intent signal (#28488) — sent as request headers to the
    // AlterLab API itself, never added to the JSON body payload.
    //
    // HTTP header values must be US-ASCII (RFC 7230); passing a non-ASCII
    // string straight to axios/Node's http module throws a TypeError before
    // the request is ever sent. Percent-encode only when needed so
    // ASCII-only values (the common case) are sent byte-identical to
    // before (#28634).
    const agentRequestHeaders: Record<string, string> = {};
    if (agentIntent !== undefined) {
      agentRequestHeaders["X-Agent-Intent"] = asciiSafeHeaderValue(agentIntent);
    }
    if (agentContext !== undefined) {
      agentRequestHeaders["X-Agent-Context"] =
        asciiSafeHeaderValue(agentContext);
    }
    if (agentFeedback !== undefined) {
      agentRequestHeaders["X-Agent-Feedback"] =
        asciiSafeHeaderValue(agentFeedback);
    }
    if (paymentSignature !== undefined) {
      agentRequestHeaders["PAYMENT-SIGNATURE"] = paymentSignature;
    }

    // Build the advanced options object — session, cookies, scroll,
    // section_filter, dom expansion, and browser automation params are all
    // nested inside `advanced` in the API schema.
    const advanced: Record<string, unknown> = {};
    if (sessionId) {
      advanced.session_id = sessionId;
    }
    if (cookies) {
      advanced.cookies = cookies;
    }
    if (scroll_to_load !== undefined) {
      advanced.scroll_to_load = scroll_to_load;
    }
    if (scroll_count !== undefined) {
      advanced.scroll_count = scroll_count;
    }
    if (section_filter !== undefined) {
      advanced.section_filter = section_filter;
    }
    if (include_iframes !== undefined) {
      advanced.include_iframes = include_iframes;
    }
    if (flatten_shadow_dom !== undefined) {
      advanced.flatten_shadow_dom = flatten_shadow_dom;
    }
    if (block_images !== undefined) {
      advanced.block_images = block_images;
    }
    if (actions !== undefined) {
      assertDownloadActionLimit(actions);
      advanced.actions = actions;
    }
    if (actions_on_error !== undefined) {
      advanced.actions_on_error = actions_on_error;
    }
    if (session_headers !== undefined) {
      advanced.session_headers = session_headers;
    }
    if (use_own_proxy !== undefined) {
      advanced.use_own_proxy = use_own_proxy;
    }
    if (use_system_proxy !== undefined) {
      advanced.use_system_proxy = use_system_proxy;
    }
    if (proxy_integration_id !== undefined) {
      advanced.proxy_integration_id = proxy_integration_id;
    }
    if (proxy_country !== undefined) {
      advanced.proxy_country = proxy_country;
    }
    // Mirror the API's sticky_session charset validator (#29555) and the Python
    // SDK's client-side guard (#29663). The handle is hashed into a proxy-username
    // segment and used as a Redis key component server-side, so it must be
    // restricted to [A-Za-z0-9_-]. Normalize (trim, empty -> omit) to match the
    // server, and fail fast locally with the same errors as the Python SDK instead
    // of forcing a server round-trip 4xx.
    if (sticky_session !== undefined) {
      const trimmed = sticky_session.trim();
      if (trimmed) {
        if (!/^[A-Za-z0-9_-]{1,128}$/.test(trimmed)) {
          throw new Error(
            "sticky_session must be 1-128 characters of letters, digits, '-' or '_'",
          );
        }
        advanced.sticky_session = trimmed;
      }
    }
    if (sticky_session_ttl !== undefined) {
      if (sticky_session_ttl < 300 || sticky_session_ttl > 7200) {
        throw new Error(
          "sticky_session_ttl must be between 300 and 7200 seconds",
        );
      }
      advanced.sticky_session_ttl = sticky_session_ttl;
    }
    if (skip_tls_verification !== undefined) {
      advanced.skip_tls_verification = skip_tls_verification;
    }
    if (remove_cookie_banners !== undefined) {
      advanced.remove_cookie_banners = remove_cookie_banners;
    }
    if (Object.keys(advanced).length > 0) {
      data.advanced = advanced;
    }

    const response = await this.requestWithRetryRaw<
      ScrapeResponse & {
        job_id?: string;
        sync_downgraded?: boolean;
        reason?: string;
      }
    >({
      method: "POST",
      url: "/api/v1/scrape",
      data,
      params: template ? { template } : undefined,
      headers:
        Object.keys(agentRequestHeaders).length > 0
          ? agentRequestHeaders
          : undefined,
    });

    const body = response.data;

    // Detect a 202 response — either a plain async job-creation ack
    // (`sync: false`, no `sync_downgraded`) or a sync-poll-timeout downgrade
    // (`sync_downgraded: true`, same {job_id, ...} shape) (#31823). Axios's
    // default `validateStatus` treats any 2xx as success, so without this
    // check a downgrade envelope would be returned to the caller typed —
    // and treated by them — as a completed `ScrapeResponse` with no content.
    if (
      response.status === 202 &&
      body &&
      typeof body === "object" &&
      "job_id" in body
    ) {
      const jobId = body.job_id as string;

      if (request.sync === false) {
        // Caller explicitly requested async — return the job envelope as-is,
        // same as before this fix. This also covers plain async job creation.
        return body as ScrapeResponse;
      }

      // Sync was requested (the default) but the server downgraded to async
      // — poll for the real result instead of handing back the bare
      // downgrade envelope, mirroring the Python SDK's existing behavior.
      if (body.sync_downgraded) {
        this.logger.debug(
          `sync_downgraded job_id=${jobId} reason=${body.reason ?? "unknown"} — polling for real result`,
        );
      }
      const job = await this.waitForJob(jobId, {
        serverWait: body.sync_downgraded ? DOWNGRADE_LONG_POLL_SECONDS : 0,
      });
      // Only fall back to the whole job envelope when `result` is truly
      // absent — an explicit `result: null` is returned as-is, mirroring
      // Python's `job.get("result", job)` (`dict.get`'s default only
      // applies when the key itself is missing, not when its value is
      // `None`) (#31888). `??` would otherwise treat `null` the same as
      // "missing" and silently substitute the envelope.
      return (
        "result" in job ? job.result : (job as unknown as ScrapeResponse)
      ) as ScrapeResponse;
    }

    return body;
  }

  /** @deprecated Use scrape() with mode: 'html' instead */
  async scrapeLight(request: ScrapeRequest): Promise<ScrapeResponse> {
    return this.scrape({ ...request, mode: "html" });
  }

  /** @deprecated Use scrape() with mode: 'js' instead */
  async scrapeJS(
    request: ScrapeRequest & { wait_for?: string; screenshot?: boolean },
  ): Promise<ScrapeResponse> {
    return this.scrape({ ...request, mode: "js", render_js: true });
  }

  /** @deprecated Use scrape() with mode: 'pdf' instead */
  async scrapePDF(request: {
    url: string;
    format?: string;
  }): Promise<ScrapeResponse> {
    return this.scrape({ url: request.url, mode: "pdf" });
  }

  private artifactTransport(): artifactHelpers.ArtifactTransport {
    return {
      request: (config) => this.requestWithRetry(config),
      baseUrl: this.baseUrl,
    };
  }

  /** Metadata of a `download` action artifact you own. */
  async getArtifact(artifactId: string): Promise<ArtifactMetadata> {
    return artifactHelpers.getArtifact(this.artifactTransport(), artifactId);
  }

  /** Short-lived signed download URL for an artifact (always absolute). */
  async getArtifactUrl(artifactId: string): Promise<ArtifactUrl> {
    return artifactHelpers.getArtifactUrl(this.artifactTransport(), artifactId);
  }

  /** Save an artifact to `path`; resolves to the path written. */
  async downloadArtifact(artifactId: string, path: string): Promise<string> {
    return artifactHelpers.downloadArtifact(
      this.artifactTransport(),
      artifactId,
      path,
    );
  }

  /** @deprecated Use scrape() with mode: 'ocr' instead */
  async scrapeOCR(request: {
    url: string;
    language?: string;
  }): Promise<ScrapeResponse> {
    return this.scrape({ url: request.url, mode: "ocr" });
  }

  /**
   * Usage statistics and balance. Pass `tag` to filter spend to one request
   * tag (adds the `tag_*` fields); `since` (ISO 8601) bounds the tag window.
   * `organizationId` is sent as the `X-Organization-Id` header when set.
   */
  async getUsage(
    options: { tag?: string; since?: string; organizationId?: string } = {},
  ): Promise<UsageStats> {
    const params: Record<string, string> = {};
    if (options.tag !== undefined) params.tag = options.tag;
    if (options.since !== undefined) params.since = options.since;
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/usage",
      ...(Object.keys(params).length ? { params } : {}),
      ...(options.organizationId !== undefined
        ? { headers: { "X-Organization-Id": options.organizationId } }
        : {}),
    });
  }

  /** Start a website crawl. Returns immediately with a crawl_id for polling. */
  async crawl(request: CrawlRequest): Promise<CrawlResponse> {
    const payload: Record<string, unknown> = {
      url: request.url,
      max_pages: request.maxPages ?? 50,
      max_depth: request.maxDepth ?? 3,
      respect_robots: request.respectRobots ?? true,
      include_subdomains: request.includeSubdomains ?? false,
    };

    if (request.tag !== undefined) payload.tag = request.tag;
    if (request.approvalId !== undefined)
      payload.approval_id = request.approvalId;
    if (request.dryRun) payload.dry_run = true;
    if (request.includePatterns)
      payload.include_patterns = request.includePatterns;
    if (request.excludePatterns)
      payload.exclude_patterns = request.excludePatterns;
    if (request.formats) payload.formats = request.formats;
    if (request.list) payload.list = request.list;
    if (request.extractionSchema)
      payload.extraction_schema = request.extractionSchema;
    if (request.extractionProfile)
      payload.extraction_profile = request.extractionProfile;
    if (request.extractionTemplate)
      payload.extraction_template = request.extractionTemplate;
    if (request.extractionProvider)
      payload.extraction_provider = request.extractionProvider;
    if (request.extractionModel !== undefined)
      payload.extraction_model = request.extractionModel;
    if (request.webhookUrl) payload.webhook_url = request.webhookUrl;
    if (request.forceRefresh !== undefined)
      payload.force_refresh = request.forceRefresh;
    if (request.tag !== undefined) payload.tag = request.tag;
    if (request.dryRun !== undefined) payload.dry_run = request.dryRun;
    if (request.budget !== undefined) payload.budget = request.budget;
    if (request.cache !== undefined) payload.cache = request.cache;
    if (request.cacheTtl !== undefined) payload.cache_ttl = request.cacheTtl;
    if (request.changeTracking !== undefined)
      payload.change_tracking = request.changeTracking;
    if (request.extraction !== undefined)
      payload.extraction = request.extraction;
    if (request.maxConcurrency !== undefined)
      payload.max_concurrency = request.maxConcurrency;
    if (request.output !== undefined) payload.output = request.output;
    if (request.priority !== undefined) payload.priority = request.priority;
    if (request.sitemap !== undefined) payload.sitemap = request.sitemap;
    if (request.sitemapPath !== undefined)
      payload.sitemap_path = request.sitemapPath;
    if (request.storage !== undefined) payload.storage = request.storage;
    if (request.webhook !== undefined) payload.webhook = request.webhook;
    if (request.headers !== undefined) payload.headers = request.headers;
    if (request.embeddings !== undefined)
      payload.embeddings = request.embeddings;
    if (request.costControls) {
      const cc: Record<string, unknown> = {
        max_credits: request.costControls.maxCredits,
        max_tier: request.costControls.maxTier,
        force_tier: request.costControls.forceTier,
      };
      if (request.costControls.timeBudget !== undefined) {
        cc.time_budget = request.costControls.timeBudget;
      }
      if (request.costControls.preferCost !== undefined) {
        cc.prefer_cost = request.costControls.preferCost;
      }
      if (request.costControls.preferSpeed !== undefined) {
        cc.prefer_speed = request.costControls.preferSpeed;
      }
      if (request.costControls.failFast !== undefined) {
        cc.fail_fast = request.costControls.failFast;
      }
      payload.cost_controls = cc;
    }
    if (request.advanced) {
      const advPayload: Record<string, unknown> = {
        render_js: request.advanced.renderJs,
        screenshot: request.advanced.screenshot,
        use_proxy: request.advanced.useProxy,
        wait_for: request.advanced.waitFor,
        timeout: request.advanced.timeout,
        scroll_to_load: request.advanced.scrollToLoad,
        scroll_count: request.advanced.scrollCount,
      };
      if (request.advanced.sectionFilter) {
        advPayload.section_filter = request.advanced.sectionFilter;
      }
      payload.advanced = advPayload;
    }

    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/crawl",
      data: payload,
    });
  }

  /**
   * Submit up to 100 URLs as one batch.
   *
   * Accepts either a full `BatchRequest` (`urls`, `session_id`, `export`,
   * batch-level extraction defaults) or the legacy `(items, webhookUrl?)` form.
   */
  async batchScrape(
    request: BatchRequest | BatchScrapeRequest[],
    webhookUrl?: string,
  ): Promise<BatchResponse> {
    const batch: BatchRequest = Array.isArray(request)
      ? { urls: request }
      : request;
    const payload: Record<string, unknown> = {
      ...batch,
      urls: batch.urls.map(toBatchItemPayload),
    };
    if (webhookUrl) {
      payload.webhook_url = webhookUrl;
    }
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/batch",
      data: payload,
    });
  }

  /**
   * Resubmit the items a batch rejected. `items` is the list you submitted;
   * rejected entries in `response.jobs` are matched back by `index`. Returns
   * `null` when nothing was rejected.
   */
  async resubmitRejected(
    items: BatchScrapeRequest[],
    response: Pick<BatchResponse, "jobs">,
    webhookUrl?: string,
  ): Promise<BatchResponse | null> {
    const retry = (response.jobs ?? [])
      .filter((job) => job.status === "rejected")
      .map((job) => items[job.index])
      .filter((item): item is BatchScrapeRequest => item !== undefined);
    if (retry.length === 0) return null;
    return this.batchScrape(retry, webhookUrl);
  }

  /** Get crawl status and optionally per-page results (paginated, filtered, sorted). */
  async getCrawl(
    crawlId: string,
    includeResults = false,
    options?: GetCrawlOptions,
  ): Promise<CrawlStatusResponse> {
    const params: Record<string, string | number> = {};
    if (includeResults) params.include_results = "true";
    if (options?.limit !== undefined) params.limit = options.limit;
    if (options?.offset !== undefined) params.offset = options.offset;
    if (options?.sort !== undefined) params.sort = options.sort;
    if (options?.status !== undefined) params.status = options.status;
    if (options?.includeDepthStats) params.include_depth_stats = "true";
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/crawl/${crawlId}`,
      params: Object.keys(params).length > 0 ? params : undefined,
    });
  }

  /** Cancel a crawl and refund credits for unprocessed pages. */
  async cancelCrawl(crawlId: string): Promise<CrawlCancelResponse> {
    return this.requestWithRetry({
      method: "DELETE",
      url: `/api/v1/crawl/${crawlId}`,
    });
  }

  /**
   * Export crawl results as a downloadable file.
   *
   * Fetches all page results for a completed (or in-progress) crawl and
   * returns them as a `Buffer` in the requested format. Suitable for saving
   * to disk or forwarding to a client as a file download.
   *
   * @param crawlId - Crawl ID returned from `crawl()`
   * @param options - Export options
   * @param options.format - Output format: `"json"` (default), `"jsonl"`, or `"csv"`
   * @param options.status - Filter by page status (default: `"succeeded"`).
   *   Use `"all"` to include every page regardless of status.
   * @param options.fields - Comma-separated list of fields to include
   *   (e.g. `"url,html,status"`). Omit for all fields.
   *
   * @returns Raw file bytes as a `Buffer`
   *
   * @throws {AlterLabAPIError} On API errors (404 if crawl not found or expired)
   *
   * @example
   * ```ts
   * // Download as JSON
   * const buf = await client.exportCrawl(crawlId, { format: "json" });
   * const rows = JSON.parse(buf.toString("utf-8"));
   *
   * // Download as CSV (all pages)
   * const csv = await client.exportCrawl(crawlId, {
   *   format: "csv",
   *   status: "all",
   * });
   * fs.writeFileSync("results.csv", csv);
   * ```
   */
  async exportCrawl(
    crawlId: string,
    options: CrawlExportOptions = {},
  ): Promise<Buffer> {
    const { format = "json", status = "succeeded", fields } = options;
    const params: Record<string, string> = { format, status };
    if (fields !== undefined) {
      params.fields = fields;
    }
    return this.requestWithRetry<Buffer>({
      method: "GET",
      url: `/api/v1/crawl/${crawlId}/export`,
      params,
      responseType: "arraybuffer",
    });
  }
  /**
   * Stream real-time crawl events via Server-Sent Events.
   *
   * Returns an async iterator that yields CrawlSSEEvent objects.
   *
   * Event types:
   * - `page.completed` — per-page result with metadata, cost, tier
   * - `page.failed` — per-page failure with error reason
   * - `crawl.progress` — periodic summary (pages done/total, cost)
   * - `crawl.completed` — final summary; iteration stops after this
   *
   * @example
   * ```ts
   * const crawl = await client.crawl({ url: "https://example.com" });
   * for await (const event of client.crawlStream(crawl.crawl_id)) {
   *   if (event.event === "page.completed") {
   *     console.log(`Scraped: ${event.data.url}`);
   *   }
   * }
   * ```
   */
  async *crawlStream(crawlId: string): AsyncGenerator<CrawlSSEEvent> {
    const url = `${this.baseUrl}/api/v1/crawl/${crawlId}/stream`;
    const response = await fetch(url, {
      headers: {
        "X-API-Key": this.apiKey,
        Accept: "text/event-stream",
      },
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(
        `SSE stream failed: ${response.status} ${response.statusText} — ${body}`,
      );
    }

    if (!response.body) {
      throw new Error("SSE stream returned empty body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "message";
    const dataLines: string[] = [];

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.replace(/\r$/, "");

          // Comment / keepalive
          if (trimmed.startsWith(":")) continue;

          // Empty line = event boundary
          if (trimmed === "") {
            if (dataLines.length > 0) {
              const dataStr = dataLines.join("\n");
              let parsed: Record<string, unknown>;
              try {
                parsed = JSON.parse(dataStr);
              } catch {
                parsed = { raw: dataStr };
              }

              const sseEvent: CrawlSSEEvent = {
                event: currentEvent as CrawlSSEEvent["event"],
                data: parsed,
              };
              yield sseEvent;

              // Terminal event
              if (currentEvent === "crawl.completed") return;

              currentEvent = "message";
              dataLines.length = 0;
            }
            continue;
          }

          if (trimmed.startsWith("event:")) {
            currentEvent = trimmed.slice(6).trim();
          } else if (trimmed.startsWith("data:")) {
            dataLines.push(trimmed.slice(5).trim());
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /** Start a crawl and wait for completion, returning all results. */
  async crawlAndWait(
    request: CrawlRequest,
    options: CrawlAndWaitOptions = {},
  ): Promise<CrawlStatusResponse> {
    const {
      pollInterval = 2000,
      pollTimeout = 600000,
      backoffMultiplier = 1.5,
      maxInterval = 15000,
    } = options;

    const crawlResponse = await this.crawl(request);
    const crawlId = crawlResponse.crawl_id;
    const start = Date.now();
    let interval = pollInterval;

    while (true) {
      const elapsed = Date.now() - start;
      if (elapsed > pollTimeout) {
        throw new Error(
          `Crawl ${crawlId} did not complete within ${pollTimeout / 1000} seconds`,
        );
      }

      await this.sleep(interval);

      const status = await this.getCrawl(crawlId, true);

      if (
        status.status === "completed" ||
        status.status === "partial" ||
        status.status === "failed"
      ) {
        return status;
      }

      interval = Math.min(interval * backoffMultiplier, maxInterval);
    }
  }

  /**
   * Get the current status of an async job without waiting.
   *
   * Use this for manual status checks. For automatic polling use `waitForJob()`.
   *
   * @throws {JobExpiredError} When the job has expired (API returns 404). Job
   *   results are retained for 1 hour after completion. Do not retry with the
   *   same job ID.
   */
  async getJobStatus(jobId: string, wait = 0): Promise<JobStatusResponse> {
    try {
      return await this.requestWithRetry({
        method: "GET",
        url: `/api/v1/jobs/${jobId}`,
        ...(wait > 0
          ? {
              params: { wait },
              timeout: (wait + 15) * 1000,
            }
          : {}),
      });
    } catch (error) {
      const axiosError = error as AxiosError;
      if (axiosError.response?.status === 404) {
        throw new JobExpiredError(jobId);
      }
      throw toTypedError(error);
    }
  }

  /**
   * Wait for an async job to complete, polling with exponential backoff.
   *
   * @returns The full {@link JobStatusResponse} envelope (`{job_id, status,
   *   result, error, ...}`) — NOT just the unwrapped result. This differs
   *   from the Python SDK's `wait_for_job()`, which returns the unwrapped
   *   `result` dict directly (or `None` if the job's `result` is explicitly
   *   `null`). This is a pre-existing, intentional cross-language asymmetry
   *   (#31887) — unify by reading `.result` off the returned envelope if you
   *   want Python-equivalent behavior in Node.
   * @throws {JobExpiredError} When the job has expired (API returns 404). Job
   *   results are retained for 1 hour after completion. Do not retry with the
   *   same job ID — create a new job instead.
   * @throws {JobFailedError} When the job reaches a terminal failure status
   *   (`failed`, `rejected`, or `cancelled`).
   * @throws {JobTimeoutError} When `pollTimeout` elapses first.
   * @throws {Error} On a status outside the known
   *   `JobStatus` vocabulary (should not happen in practice).
   */
  async waitForJob(
    jobId: string,
    options: WaitForJobOptions = {},
  ): Promise<JobStatusResponse> {
    const {
      pollInterval = 2000,
      pollTimeout = 300000,
      backoffMultiplier = 1.5,
      maxInterval = 30000,
      serverWait = 0,
    } = options;

    const start = Date.now();
    let interval = pollInterval;

    while (true) {
      const elapsed = Date.now() - start;
      if (elapsed > pollTimeout) {
        throw new JobTimeoutError(jobId, pollTimeout / 1000);
      }

      const pollStarted = Date.now();
      const job = await this.getJobStatus(jobId, serverWait);

      if (job.status === "succeeded" || job.status === "completed") {
        return job;
      }
      if (
        job.status === "failed" ||
        job.status === "rejected" ||
        job.status === "cancelled"
      ) {
        const jobError = job.error;
        const detail =
          jobError && typeof jobError === "object"
            ? String(
                (jobError as Record<string, unknown>).message ??
                  JSON.stringify(jobError),
              )
            : jobError || `Job ended with status '${job.status}'`;
        throw new JobFailedError(
          jobId,
          job.status,
          detail,
          errorObjectHint(jobError),
          {
            error: jobError,
            next_action: (job as { next_action?: unknown }).next_action,
          },
        );
      }
      if (
        job.status !== "pending" &&
        job.status !== "queued" &&
        job.status !== "running" &&
        job.status !== "retrying"
      ) {
        throw new Error(`Unknown job status: ${job.status}`);
      }

      // A long-poll that held the request open already did the waiting;
      // servers that ignore `wait` answer at once, so back off as before.
      if (serverWait > 0 && Date.now() - pollStarted >= 1000) {
        continue;
      }
      await this.sleep(interval);
      interval = Math.min(interval * backoffMultiplier, maxInterval);
    }
  }

  async estimateCost(
    request: CostEstimateRequest,
  ): Promise<CostEstimateResponse> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/scrape/estimate",
      data: request,
    });
  }

  /** Discover URLs on a website via sitemap parsing and link extraction. */
  async map(request: MapRequest): Promise<MapResponse> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/map",
      data: request,
    });
  }

  /**
   * Search the web: unified, vendor-neutral results with page content by default.
   *
   * A plain `search({ query })` runs the unified search (`engine: "auto"`) on `/v1/search` and
   * returns each result page as concise markdown with a per-result `content_status`
   * (`scrape_results: true`, `concise: true`, `mode: "standard"`). Pass `scrape_results: false`
   * for the result list only. An explicit `engine` of duckduckgo, google or bing keeps that
   * engine's behaviour: content is only fetched when asked for, and plain requests use
   * `/v1/serp`.
   */
  async search(request: SearchRequest): Promise<SearchResponse | MultiSearchResponse> {
    if ((request.query === undefined) === (request.queries === undefined)) {
      throw new Error("search() takes exactly one of query or queries");
    }
    const engine = request.engine ?? "auto";
    const scrapeResults =
      request.scrape_results ?? (engine === "auto" && request.queries === undefined);
    const useSerp =
      request.queries === undefined &&
      !scrapeResults &&
      request.domain === undefined &&
      request.time_range === undefined &&
      engine !== "auto"; // unified search is only served by /v1/search
    const { num, device, concise, ...rest } = request;
    const data: Record<string, unknown> = { ...rest, engine, scrape_results: scrapeResults };
    if (scrapeResults && engine === "auto") {
      if (concise !== false && request.formats === undefined && request.preset === undefined) {
        data.preset = "agent";
      }
      if (request.wait === undefined && request.mode === undefined) data.mode = "standard";
    }
    if (num !== undefined) data.num_results = num;
    if (device !== undefined && useSerp) data.device = device;
    return this.requestWithRetry({
      method: "POST",
      url: useSerp ? "/api/v1/serp" : "/api/v1/search",
      data,
    });
  }

  /** Start a research job on the caller's own model key (POST /api/v1/research). */
  async research(request: ResearchRequest): Promise<ResearchJob> {
    return this.requestWithRetry<ResearchJob>({
      method: "POST",
      url: "/api/v1/research",
      data: request,
    });
  }

  /** Fetch a research job: status, cost, coverage, warnings and (when done) the result. */
  async getResearch(jobId: string): Promise<ResearchJob> {
    return this.requestWithRetry<ResearchJob>({ method: "GET", url: `/api/v1/research/${jobId}` });
  }

  /** Cancel a queued or running research job. */
  async cancelResearch(jobId: string): Promise<ResearchJob> {
    return this.requestWithRetry<ResearchJob>({
      method: "POST",
      url: `/api/v1/research/${jobId}/cancel`,
    });
  }

  /**
   * Poll until the job is completed, completed_partial, failed, cancelled or awaiting approval.
   * Rejects when `timeoutMs` elapses first (the job keeps running).
   */
  async waitForResearch(jobId: string, options: WaitForResearchOptions = {}): Promise<ResearchJob> {
    const { pollIntervalMs = 2000, timeoutMs = 600000 } = options;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const job = await this.getResearch(jobId);
      if (RESEARCH_SETTLED_STATUSES.includes(job.status)) return job;
      if (Date.now() + pollIntervalMs > deadline) {
        throw new Error(`Research job ${jobId} still ${job.status} after ${timeoutMs}ms`);
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  }

  /** Progress events of a job; pass the last seen `id` as `lastEventId` to get only newer ones. */
  async researchEvents(jobId: string, lastEventId?: string): Promise<ResearchEvent[]> {
    const text = await this.requestWithRetry<string>({
      method: "GET",
      url: `/api/v1/research/${jobId}/events`,
      headers: lastEventId ? { "Last-Event-ID": lastEventId } : undefined,
      responseType: "text",
      transformResponse: (data: unknown) => data,
    });
    return parseSseEvents(String(text));
  }

  /** The plan of a `plan_first` job. */
  async getResearchPlan(jobId: string): Promise<Record<string, unknown>> {
    return this.requestWithRetry({ method: "GET", url: `/api/v1/research/${jobId}/plan` });
  }

  /** Replace the plan of a job awaiting approval. */
  async updateResearchPlan(
    jobId: string,
    plan: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "PUT",
      url: `/api/v1/research/${jobId}/plan`,
      data: { plan },
    });
  }

  /** Approve the plan (optionally replacing it) and start the run. */
  async approveResearch(jobId: string, plan?: Record<string, unknown>): Promise<ResearchJob> {
    return this.requestWithRetry<ResearchJob>({
      method: "POST",
      url: `/api/v1/research/${jobId}/approve`,
      data: plan === undefined ? undefined : { plan },
    });
  }

  /**
   * Report friction to AlterLab (POST /api/v1/agent/feedback). `category` prefixes
   * the clustered `happened` text and `jobId` is appended to `tried`; free text is
   * capped at 1000 characters. Never include customer data.
   */
  async feedback(request: FeedbackRequest): Promise<FeedbackResponse> {
    const limit = 1000;
    let tried = request.tried ?? "";
    if (request.jobId) tried = `${tried} job_id=${request.jobId}`.trim();
    const data: Record<string, unknown> = {
      what_failed: (
        request.what_failed ?? `[${request.category}] ${request.happened}`
      ).slice(0, limit),
      surface: request.surface ?? "sdk",
    };
    tried = request.what_tried ?? tried;
    const expected = request.what_expected ?? request.expected;
    if (tried) data.what_tried = tried.slice(0, limit);
    if (expected) data.what_expected = expected.slice(0, limit);
    if (request.suggestion)
      data.suggestion = request.suggestion.slice(0, limit);
    if (request.toolName) data.tool_name = request.toolName.slice(0, 100);
    if (request.url) data.url = request.url.slice(0, 2000);
    if (request.dry_run) data.dry_run = true;
    if (request.same_as) data.same_as = request.same_as.slice(0, 64);
    if (request.new) data.new = true;
    const res = await this.requestWithRetry<
      Omit<FeedbackResponse, "statusUrl">
    >({
      method: "POST",
      url: "/api/v1/agent/feedback",
      data,
    });
    const base = String(this.client.defaults.baseURL ?? "").replace(/\/+$/, "");
    return {
      ...res,
      statusUrl: `${base}/api/v1/agent/feedback/${res.cluster_key}`,
    };
  }

  /** Public price list (`GET /api/v1/pricing`). */
  pricing() {
    return this.parity.pricing();
  }
  /** News search (`GET /api/v1/news`): q, category, source, language, since, limit. */
  news(params?: Parameters<McpParity["news"]>[0]) {
    return this.parity.news(params);
  }
  /** Keyword ideas (`POST /api/v1/serp/keyword-ideas`). */
  keywordIdeas(fields: Parameters<McpParity["keywordIdeas"]>[0]) {
    return this.parity.keywordIdeas(fields);
  }
  /** Structured search results (`POST /api/v1/serp`). */
  serp(query: string, fields?: Parameters<McpParity["serp"]>[1]) {
    return this.parity.serp(query, fields);
  }
  aiVisibility(...args: Parameters<McpParity["aiVisibility"]>) {
    return this.parity.aiVisibility(...args);
  }
  screenshot(...args: Parameters<McpParity["screenshot"]>) {
    return this.parity.screenshot(...args);
  }
  /** Alias of `support.ticket()`. */
  supportTicket(request: SupportTicketRequest) {
    return this.support.ticket(request);
  }
  /** Alias of `jobs.report()`. */
  reportScrape(
    jobId: string,
    issueType: ScrapeIssueType,
    options?: ReportScrapeOptions,
  ) {
    return this.jobs.report(jobId, issueType, options);
  }

  /** Submit a batch of search queries for async processing. */
  async batchSearch(request: BatchSearchRequest): Promise<BatchSearchResponse> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/search/batch",
      data: request,
    });
  }

  /** Poll a search started with `scrape_results: true`. */
  async getSearch(searchId: string): Promise<SearchStatusResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/search/${searchId}`,
    });
  }

  /** Poll a batch search for per-query status and results. */
  async getBatchSearch(batchId: string): Promise<BatchSearchStatusResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/search/batch/${batchId}`,
    });
  }

  /**
   * Poll a batch (`GET /v1/batch/{batch_id}`). `paused` counts items held back
   * by the `paused_low_success` stop; `paused_reason` says why. `submitted` and
   * `rejected_items` report URLs that got no job.
   *
   * Poll with `{ include: "counts" }` for a small response; the default
   * (`"items"`) lists items without result bodies (each has a `result_url`);
   * `"results"` inlines every result. `limit`/`offset` page the items.
   */
  async getBatchStatus(
    batchId: string,
    options: {
      include?: "counts" | "items" | "results";
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<BatchStatusResponse> {
    const params: Record<string, string | number> = {};
    if (options.include !== undefined) params.include = options.include;
    if (options.limit !== undefined) params.limit = options.limit;
    if (options.offset !== undefined) params.offset = options.offset;
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/batch/${batchId}`,
      ...(Object.keys(params).length ? { params } : {}),
    });
  }

  /** Re-enqueue items a batch paused with `paused_low_success`. */
  async resumeBatch(batchId: string): Promise<BatchResumeResponse> {
    return this.requestWithRetry({
      method: "POST",
      url: `/api/v1/batch/${batchId}/resume`,
    });
  }

  /** Poll a spend approval raised by `approval_above_usd` (GET /api/v1/approvals/{id}). */
  async getApproval(approvalId: string): Promise<ApprovalStatus> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/approvals/${encodeURIComponent(approvalId)}`,
    });
  }

  /** Read a request tag's `approval_above_usd` threshold. */
  async getTagApproval(tag: string): Promise<TagApproval> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/usage-tags/${encodeURIComponent(tag)}/approval`,
    });
  }

  /** Set (or clear with `null`) a request tag's `approval_above_usd` threshold. */
  async setTagApproval(
    tag: string,
    approvalAboveUsd: number | null,
  ): Promise<TagApproval> {
    return this.requestWithRetry({
      method: "PUT",
      url: `/api/v1/usage-tags/${encodeURIComponent(tag)}/approval`,
      data: { approval_above_usd: approvalAboveUsd },
    });
  }

  /** Set spend limits for an API key (`PUT /api/v1/api-keys/{key_id}/limits`). */
  async setKeyLimits(
    keyId: string,
    limits: SpendLimitConfig,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "PUT",
      url: `/api/v1/api-keys/${encodeURIComponent(keyId)}/limits`,
      data: limits,
    });
  }

  /** Set account-wide spend limits (`PUT /api/v1/account/limits`). */
  async setAccountLimits(
    limits: SpendLimitConfig,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "PUT",
      url: "/api/v1/account/limits",
      data: limits,
    });
  }

  /** Set spend limits for an OAuth grant (`PUT /api/v1/oauth-grants/{grant_id}/limits`). */
  async setGrantLimits(
    grantId: string,
    limits: SpendLimitConfig,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "PUT",
      url: `/api/v1/oauth-grants/${encodeURIComponent(grantId)}/limits`,
      data: limits,
    });
  }

  /** Run actions on a Hands task (`POST /api/v1/hands/tasks/{task_id}/act`). */
  async handsAct(
    taskId: string,
    request: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "POST",
      url: `/api/v1/hands/tasks/${encodeURIComponent(taskId)}/act`,
      data: request,
    });
  }

  /** Vision-guided action on a Hands task (`POST /api/v1/hands/tasks/{task_id}/vision/act`). */
  async handsVisionAct(
    taskId: string,
    request: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "POST",
      url: `/api/v1/hands/tasks/${encodeURIComponent(taskId)}/vision/act`,
      data: request,
    });
  }

  /** Create a Hands growth run (`POST /api/v1/hands/growth-run`). */
  async createGrowthRun(
    request: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/hands/growth-run",
      data: request,
    });
  }

  /** Extract structured data from raw content without scraping. */
  async extract(request: ExtractRequest): Promise<ExtractResponse> {
    return this.requestWithRetry({
      method: "POST",
      url: "/api/v1/extract",
      data: request,
    });
  }

  // ---------------------------------------------------------------------------
  // Extraction estimate, usage, and template methods
  // ---------------------------------------------------------------------------

  /**
   * Estimate the cost of a POST /v1/extract call before committing to it.
   *
   * Read-only — does not require a BYOK key and does not modify balance.
   *
   * @param contentLength - Length of the content in characters (1–5,000,000)
   * @param hasExtractionPrompt - Whether an extraction_prompt or LLM profile will be used
   */
  async estimateExtractionCost(
    contentLength: number,
    hasExtractionPrompt = false,
  ): Promise<ExtractionEstimateResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/extract/estimate",
      params: {
        content_length: contentLength,
        has_extraction_prompt: hasExtractionPrompt,
      },
    });
  }

  /**
   * Get paginated extraction usage history for the authenticated user.
   *
   * Results are ordered by created_at DESC (newest first).
   */
  async getExtractionUsage(options?: {
    page?: number;
    pageSize?: number;
    dateFrom?: string;
    dateTo?: string;
  }): Promise<ExtractionUsageListResponse> {
    const params: Record<string, unknown> = {};
    if (options?.page !== undefined) params.page = options.page;
    if (options?.pageSize !== undefined) params.page_size = options.pageSize;
    if (options?.dateFrom !== undefined) params.date_from = options.dateFrom;
    if (options?.dateTo !== undefined) params.date_to = options.dateTo;
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/extract/usage",
      params,
    });
  }

  /**
   * Get aggregate extraction usage totals for the authenticated user.
   *
   * @param hours - Look back N hours (mutually exclusive with days)
   * @param days - Look back N days (mutually exclusive with hours)
   */
  async getExtractionUsageSummary(options?: {
    hours?: number;
    days?: number;
  }): Promise<ExtractionUsageSummaryResponse> {
    const params: Record<string, unknown> = {};
    if (options?.hours !== undefined) params.hours = options.hours;
    if (options?.days !== undefined) params.days = options.days;
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/extract/usage/summary",
      params,
    });
  }

  // ── Scrape Templates (public, no auth required) ──────────────────────

  /**
   * List public scrape templates with optional tag filtering.
   *
   * No authentication required.
   *
   * @param options - Pagination and filter options.
   * @returns Paginated list of scrape templates.
   */
  async listScrapeTemplates(
    options?: ScrapeTemplateListOptions,
  ): Promise<ScrapeTemplateListResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: "/api/v1/templates",
      params: options,
    });
  }

  /**
   * Get a single public scrape template by its slug.
   *
   * No authentication required.
   *
   * @param slug - URL-safe unique identifier of the template.
   * @returns The scrape template detail.
   */
  async getScrapeTemplate(slug: string): Promise<ScrapeTemplateDetailResponse> {
    return this.requestWithRetry({
      method: "GET",
      url: `/api/v1/templates/${slug}`,
    });
  }
}

export * from "./actions";
export * from "./mcpNamespaces";
export * from "./artifacts";
export * from "./document.generated";

// ---------------------------------------------------------------------------
// Drop-in fetch()-compatible wrapper
// ---------------------------------------------------------------------------

export {
  createFetch,
  fetch,
  AlterLabFetchResponse,
  AlterLabFetchHeaders,
  type AlterLabFetchOptions,
  type AlterLabFetchRequestInit,
  type AlterLabFetchFunction,
} from "./fetch-compat";
export { verifyReceipt, canonicalJson } from "./hands-receipts";
export type { HandsReceipt, ReceiptKey, ReceiptKeySet, ReceiptVerification } from "./hands-receipts";
