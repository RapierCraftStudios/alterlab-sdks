import { isBlocked } from "./detector";

export const SOURCE = "unblock-fetch";
export const VERSION = "0.1.0";
const DEFAULT_BASE_URL = "https://api.alterlab.io";
export const DEFAULT_GET_KEY_URL =
  "https://alterlab.io/signup?source=unblock-fetch&utm_source=unblock-fetch" +
  "&utm_medium=sdk&utm_campaign=keyless-fallback";
const NEXT_ACTION = "Get a free key at get_key_url and set ALTERLAB_API_KEY to keep unblocking.";

export interface UnblockResponse {
  status: number;
  ok: boolean;
  url: string;
  headers: Record<string, string>;
  text: string;
  via: "direct" | "alterlab";
  attribution?: Record<string, string>;
  get_key_url?: string;
  next_action?: string;
  json(): unknown;
}

export interface UnblockOptions {
  headers?: Record<string, string>;
  /** Milliseconds. */
  timeout?: number;
  apiKey?: string;
  baseUrl?: string;
  fetch?: typeof fetch;
}

// One keyless trial key per process and base URL.
const trialKeys = new Map<string, string>();
export function resetTrialKeys(): void {
  trialKeys.clear();
}

function build(r: Omit<UnblockResponse, "ok" | "json">): UnblockResponse {
  return { ...r, ok: r.status < 400, json: () => JSON.parse(r.text) };
}

function pageText(result: any): string {
  const c = result?.content;
  if (c && typeof c === "object") return c.markdown || c.text || c.html || "";
  return typeof c === "string" ? c : "";
}

async function scrape(f: typeof fetch, base: string, key: string, url: string, timeout: number) {
  const headers = {
    "X-API-Key": key,
    "X-AlterLab-Source": `${SOURCE}/${VERSION}`,
    "Content-Type": "application/json",
  };
  let resp = await f(`${base}/api/v1/scrape`, {
    method: "POST",
    headers,
    body: JSON.stringify({ url, sync: true }),
    signal: AbortSignal.timeout(timeout + 30000),
  });
  if (resp.status === 202) {
    const jobId = ((await resp.json()) as any)?.job_id;
    const deadline = Date.now() + timeout + 30000;
    while (jobId && Date.now() < deadline) {
      resp = await f(`${base}/api/v1/jobs/${jobId}?wait=10`, {
        headers,
        signal: AbortSignal.timeout(30000),
      });
      if (resp.status === 200) {
        const body = (await resp.clone().json()) as any;
        if (!["pending", "queued", "running", "processing"].includes(body?.status)) break;
      }
    }
  }
  return resp.status === 200 ? ((await resp.json()) as any) : null;
}

async function keylessKey(
  f: typeof fetch,
  base: string,
): Promise<{ key?: string; getKeyUrl?: string }> {
  const cached = trialKeys.get(base);
  if (cached) return { key: cached };
  const resp = await f(`${base}/api/v1/agent/trial`, {
    method: "POST",
    headers: { "X-AlterLab-Source": `${SOURCE}/${VERSION}` },
    signal: AbortSignal.timeout(15000),
  });
  const body: any = await resp.json().catch(() => ({}));
  if (resp.status === 201 && body.key) {
    trialKeys.set(base, body.key);
    return { key: body.key };
  }
  return { getKeyUrl: body?.detail?.get_key_url };
}

/** Drop-in for `fetch(url, { headers })` that returns the same fields plus `via`. */
export async function unblockFetch(
  url: string,
  opts: UnblockOptions = {},
): Promise<UnblockResponse> {
  const f = opts.fetch ?? fetch;
  const timeout = opts.timeout ?? 20000;
  const direct = await f(url, { headers: opts.headers, signal: AbortSignal.timeout(timeout) });
  const text = await direct.text();
  const headers: Record<string, string> = {};
  direct.headers.forEach((v, k) => (headers[k] = v));
  const original = (extra: Partial<UnblockResponse> = {}) =>
    build({
      status: direct.status,
      url: direct.url || url,
      headers,
      text,
      via: "direct",
      ...extra,
    });
  if (!isBlocked(direct.status, text)) return original();

  const base = (opts.baseUrl ?? process.env.ALTERLAB_BASE_URL ?? DEFAULT_BASE_URL).replace(
    /\/+$/,
    "",
  );
  const userKey = opts.apiKey ?? process.env.ALTERLAB_API_KEY;
  let result: any = null;
  let getKeyUrl: string | undefined;
  try {
    let key = userKey;
    if (!key) ({ key, getKeyUrl } = await keylessKey(f, base));
    if (key) result = await scrape(f, base, key, url, timeout);
  } catch {
    result = null;
  }
  if (!result)
    return original({ get_key_url: getKeyUrl || DEFAULT_GET_KEY_URL, next_action: NEXT_ACTION });
  return build({
    status: Number(result.status_code) || 200,
    url,
    headers: {},
    text: pageText(result),
    via: "alterlab",
    attribution: {
      source: SOURCE,
      utm_source: SOURCE,
      utm_medium: "sdk",
      utm_campaign: "keyless-fallback",
    },
    get_key_url: DEFAULT_GET_KEY_URL,
    ...(userKey ? {} : { next_action: NEXT_ACTION }),
  });
}
