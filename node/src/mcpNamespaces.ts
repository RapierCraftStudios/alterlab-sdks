/**
 * MCP-parity namespaces (#40286): thin typed wrappers over REST routes the MCP
 * server also exposes. Nothing here files feedback or tickets on its own;
 * `onUnexpectedResponse` only notifies the caller.
 */
import type { AxiosRequestConfig } from "axios";

export type Requester = <T>(config: AxiosRequestConfig) => Promise<T>;

export interface UnexpectedResponseInfo {
  method: string;
  path: string;
  reason: string;
}
export type UnexpectedResponseHook = (info: UnexpectedResponseInfo) => void;

export const SCRAPE_ISSUE_TYPES = [
  "captcha_page",
  "incomplete_scrape",
  "blocked",
  "wrong_content",
  "slow_response",
  "extraction_error",
  "encoding_error",
  "other",
] as const;
export type ScrapeIssueType = (typeof SCRAPE_ISSUE_TYPES)[number];

export interface SupportTicketRequest {
  subject: string;
  body: string;
  categorySlug?: string;
  /** Default true: the agent files this because its user asked for help. */
  onBehalfOfUser?: boolean;
  toolName?: string;
  jobId?: string;
}

export interface ReportScrapeOptions {
  description?: string;
  expectedContent?: string;
}

type Fields = Record<string, unknown>;

const seg = (v: string): string => encodeURIComponent(String(v));
const clean = (fields: Fields): Fields =>
  Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== undefined));

class Base {
  constructor(
    private requester: Requester,
    private hook: () => UnexpectedResponseHook | undefined,
  ) {}

  protected async call<T = unknown>(
    method: string,
    path: string,
    opts: { params?: Fields; data?: Fields } = {},
  ): Promise<T> {
    const config: AxiosRequestConfig = { method, url: path };
    if (opts.params && Object.keys(opts.params).length) {
      config.params = opts.params;
    }
    if (opts.data !== undefined) config.data = opts.data;
    const res = await this.requester<T>(config);
    if (
      res !== "" &&
      res !== undefined &&
      (res === null || typeof res !== "object")
    ) {
      this.hook()?.({ method, path, reason: "not a JSON object" });
    }
    return res;
  }
}

export class AccountNamespace extends Base {
  /** Wallet balance (`GET /api/v1/billing/balance`). */
  balance(): Promise<Fields> {
    return this.call("GET", "/api/v1/billing/balance");
  }
  /** Usage statistics (`GET /api/v1/usage`). */
  usage(): Promise<Fields> {
    return this.call("GET", "/api/v1/usage");
  }
}

export class SupportNamespace extends Base {
  /** Open a real support ticket (`POST /api/v1/agent/support-ticket`). */
  ticket(request: SupportTicketRequest): Promise<Fields> {
    return this.call("POST", "/api/v1/agent/support-ticket", {
      data: clean({
        subject: request.subject.slice(0, 200),
        body: request.body.slice(0, 5000),
        category_slug: request.categorySlug,
        on_behalf_of_user: request.onBehalfOfUser ?? true,
        tool_name: request.toolName,
        job_id: request.jobId,
      }),
    });
  }
}

export class JobsNamespace extends Base {
  /** Report a bad scrape result (`POST /api/v1/feedback/scrape`). */
  report(
    jobId: string,
    issueType: ScrapeIssueType,
    options: ReportScrapeOptions = {},
  ): Promise<Fields> {
    if (!(SCRAPE_ISSUE_TYPES as readonly string[]).includes(issueType)) {
      throw new Error(
        `issueType must be one of: ${SCRAPE_ISSUE_TYPES.join(", ")}`,
      );
    }
    return this.call("POST", "/api/v1/feedback/scrape", {
      data: clean({
        job_id: jobId,
        issue_type: issueType,
        description: options.description?.slice(0, 2000),
        expected_content: options.expectedContent?.slice(0, 1000),
      }),
    });
  }
  /** Why a job ended as it did (`GET /api/v1/jobs/{id}/explain`). */
  explain(jobId: string): Promise<Fields> {
    return this.call("GET", `/api/v1/jobs/${seg(jobId)}/explain`);
  }
}

class Collection extends Base {
  protected base = "";
  list(params: Fields = {}): Promise<unknown> {
    return this.call("GET", this.base, { params: clean(params) });
  }
  create(fields: Fields): Promise<Fields> {
    return this.call("POST", this.base, { data: clean(fields) });
  }
  delete(id: string): Promise<unknown> {
    return this.call("DELETE", `${this.base}/${seg(id)}`);
  }
}

/** `/api/v1/monitors` (name, url, check_interval, ...). */
export class MonitorsNamespace extends Collection {
  protected base = "/api/v1/monitors";
}

/** `/api/v1/schedules` (name, urls, cron, ...). */
export class SchedulesNamespace extends Collection {
  protected base = "/api/v1/schedules";
}

export class StoreNamespace extends Base {
  search(params: Fields = {}): Promise<unknown> {
    return this.call("GET", "/api/v1/listings", { params: clean(params) });
  }
  get(slug: string, version?: string): Promise<unknown> {
    return this.call("GET", `/api/v1/listings/${seg(slug)}`, {
      params: clean({ version }),
    });
  }
  quote(slug: string, opts: { maxResults?: number; version?: string } = {}) {
    return this.call("POST", `/api/v1/listings/${seg(slug)}/quote`, {
      data: clean({ max_results: opts.maxResults, version: opts.version }),
    });
  }
  /** Run a listing; this spends credits. */
  run(
    slug: string,
    opts: {
      input?: Fields;
      maxResults?: number;
      wait?: boolean;
      version?: string;
    } = {},
  ) {
    return this.call("POST", `/api/v1/listings/${seg(slug)}/run`, {
      params: clean({ wait: String(opts.wait ?? true), version: opts.version }),
      data: clean({ input: opts.input ?? {}, max_results: opts.maxResults }),
    });
  }
}

export class FeedsNamespace extends Base {
  list(slug: string): Promise<unknown> {
    return this.call("GET", `/api/v1/listings/${seg(slug)}/feeds`);
  }
  create(slug: string, fields: Fields): Promise<unknown> {
    return this.call("POST", `/api/v1/listings/${seg(slug)}/feeds`, {
      data: clean(fields),
    });
  }
  update(slug: string, feedId: string, fields: Fields): Promise<unknown> {
    return this.call(
      "PATCH",
      `/api/v1/listings/${seg(slug)}/feeds/${seg(feedId)}`,
      { data: clean(fields) },
    );
  }
  delete(slug: string, feedId: string): Promise<unknown> {
    return this.call(
      "DELETE",
      `/api/v1/listings/${seg(slug)}/feeds/${seg(feedId)}`,
    );
  }
  deltas(
    feedId: string,
    opts: { page?: number; pageSize?: number } = {},
  ): Promise<unknown> {
    return this.call("GET", `/api/v1/listings/feeds/${seg(feedId)}/deltas`, {
      params: clean({ page: opts.page, page_size: opts.pageSize }),
    });
  }
}

export class WorkflowsNamespace extends Base {
  run(workflowId: string, inputData: Fields = {}): Promise<unknown> {
    return this.call("POST", `/api/v1/workflows/${seg(workflowId)}/run`, {
      data: { input_data: inputData },
    });
  }
}

/** Top-level MCP-parity methods; `AlterLab` delegates to these. */
export class McpParity extends Base {
  pricing(): Promise<Fields> {
    return this.call("GET", "/api/v1/pricing");
  }
  news(params: Fields = {}): Promise<unknown> {
    return this.call("GET", "/api/v1/news", { params: clean(params) });
  }
  keywordIdeas(fields: Fields): Promise<unknown> {
    return this.call("POST", "/api/v1/serp/keyword-ideas", {
      data: clean(fields),
    });
  }
  serp(query: string, fields: Fields = {}): Promise<unknown> {
    return this.call("POST", "/api/v1/serp", {
      data: clean({ query, ...fields }),
    });
  }
  /** `check`/`quote` POST; `status`/`results` GET and need `runId`. */
  aiVisibility(
    action: "check" | "quote" | "status" | "results",
    fields: Fields & { runId?: string } = {},
  ): Promise<unknown> {
    const { runId, ...rest } = fields;
    const base = "/api/v1/ai-visibility";
    if (action === "check" || action === "quote") {
      return this.call("POST", `${base}/${action}`, { data: clean(rest) });
    }
    if ((action === "status" || action === "results") && runId) {
      const suffix = action === "results" ? "/results" : "";
      return this.call("GET", `${base}/runs/${seg(runId)}${suffix}`);
    }
    throw new Error("action must be check|quote, or status|results with runId");
  }
  /** Render `url` and return the job with `screenshot_url`. */
  screenshot(
    url: string,
    opts: { waitUntil?: string; waitFor?: string; actions?: unknown[] } = {},
  ): Promise<Fields> {
    const advanced: Fields = { render_js: true, screenshot: true };
    if (opts.actions?.length) advanced.actions = opts.actions;
    return this.call("POST", "/api/v1/scrape", {
      data: clean({
        url,
        mode: "js",
        sync: true,
        screenshot: true,
        wait_until: opts.waitUntil ?? "networkidle",
        wait_for: opts.waitFor,
        advanced,
      }),
    });
  }
}

export function createParity(
  requester: Requester,
  hook: () => UnexpectedResponseHook | undefined,
) {
  return {
    parity: new McpParity(requester, hook),
    account: new AccountNamespace(requester, hook),
    support: new SupportNamespace(requester, hook),
    jobs: new JobsNamespace(requester, hook),
    monitors: new MonitorsNamespace(requester, hook),
    schedules: new SchedulesNamespace(requester, hook),
    store: new StoreNamespace(requester, hook),
    feeds: new FeedsNamespace(requester, hook),
    workflows: new WorkflowsNamespace(requester, hook),
  };
}
