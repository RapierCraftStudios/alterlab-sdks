import { isBlocked, unblockFetch } from "../src";
import { resetTrialKeys } from "../src/client";

const CLOUDFLARE =
  "<html><head><title>Just a moment...</title></head><body>challenge-platform</body></html>";
const DATADOME =
  "<html><body><script src='https://geo.captcha-delivery.com/c.js'></script>datadome</body></html>";
const CAPTCHA = "<html><body><div class='g-recaptcha'></div>Please solve the CAPTCHA</body></html>";
const JS_SHELL =
  "<html><head><script src='/app.js'></script></head><body><div id='root'></div></body></html>";
const REAL =
  "<html><body><h1>Products</h1>" +
  "<p>A perfectly ordinary page of text.</p>".repeat(10) +
  "</body></html>";

describe("isBlocked", () => {
  test.each([
    [403, CLOUDFLARE],
    [503, CLOUDFLARE],
    [200, DATADOME],
    [200, CAPTCHA],
    [200, JS_SHELL],
    [429, ""],
    [200, ""],
  ])("blocked: %s", (status, body) => expect(isBlocked(status, body)).toBe(true));

  test.each([
    [404, "<html><body>Not found</body></html>"],
    [404, ""],
    [500, "oops"],
    [200, REAL],
    [503, "Service temporarily unavailable"],
  ])("not blocked: %s", (status, body) => expect(isBlocked(status, body)).toBe(false));
});

function server(direct: Response, trial?: Response, scrape?: Response) {
  const calls: { path: string; headers: Record<string, string> }[] = [];
  const f = (async (input: any, init?: any) => {
    const u = new URL(String(input));
    if (u.host === "target.test") return direct.clone();
    calls.push({ path: u.pathname, headers: { ...(init?.headers ?? {}) } });
    if (u.pathname === "/api/v1/agent/trial") return trial!.clone();
    if (u.pathname === "/api/v1/scrape") return scrape!.clone();
    return new Response("", { status: 404 });
  }) as unknown as typeof fetch;
  return { f, calls };
}
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const SCRAPED = () => json(200, { content: { markdown: "# real page" } });
const TRIAL_OK = () => json(201, { key: "sk_trial_x" });

beforeEach(() => {
  resetTrialKeys();
  delete process.env.ALTERLAB_API_KEY;
});

test("direct success makes zero API calls", async () => {
  process.env.ALTERLAB_API_KEY = "k";
  const s = server(new Response(REAL, { status: 200 }));
  const r = await unblockFetch("https://target.test/", { fetch: s.f });
  expect(r.via).toBe("direct");
  expect(r.text).toContain("Products");
  expect(s.calls).toHaveLength(0);
});

test("plain 404 does not fall back", async () => {
  const s = server(new Response("<html><body>Not found</body></html>", { status: 404 }));
  const r = await unblockFetch("https://target.test/x", { fetch: s.f });
  expect(r.via).toBe("direct");
  expect(r.status).toBe(404);
  expect(s.calls).toHaveLength(0);
});

test("blocked with a key uses the user's key", async () => {
  process.env.ALTERLAB_API_KEY = "mykey";
  const s = server(new Response(CLOUDFLARE, { status: 403 }), undefined, SCRAPED());
  const r = await unblockFetch("https://target.test/", { fetch: s.f });
  expect(r.via).toBe("alterlab");
  expect(r.text).toBe("# real page");
  expect(s.calls.map((c) => c.path)).toEqual(["/api/v1/scrape"]);
  expect(s.calls[0].headers["X-API-Key"]).toBe("mykey");
  expect(r.attribution?.source).toBe("unblock-fetch");
  expect(r.get_key_url).toContain("unblock-fetch");
});

test("blocked keyless mints a trial key tagged unblock-fetch", async () => {
  const s = server(new Response(CLOUDFLARE, { status: 403 }), TRIAL_OK(), SCRAPED());
  const r = await unblockFetch("https://target.test/", { fetch: s.f });
  expect(r.via).toBe("alterlab");
  expect(r.next_action).toBeTruthy();
  expect(s.calls[0].path).toBe("/api/v1/agent/trial");
  expect(s.calls[0].headers["X-AlterLab-Source"]).toMatch(/^unblock-fetch\//);
  expect(s.calls[1].headers["X-API-Key"]).toBe("sk_trial_x");
});

test("over the cap returns the original response with get_key_url and no scrape", async () => {
  const capped = json(429, {
    detail: { error: "unblock_fetch_keyless_cap", get_key_url: "https://alterlab.io/signup?x=1" },
  });
  const s = server(new Response(CLOUDFLARE, { status: 403 }), capped, SCRAPED());
  const r = await unblockFetch("https://target.test/", { fetch: s.f });
  expect(r.via).toBe("direct");
  expect(r.status).toBe(403);
  expect(r.text).toBe(CLOUDFLARE);
  expect(r.get_key_url).toBe("https://alterlab.io/signup?x=1");
  expect(r.next_action).toBeTruthy();
  expect(s.calls.map((c) => c.path)).toEqual(["/api/v1/agent/trial"]);
});

test("scrape failure returns the original response", async () => {
  const s = server(
    new Response(CLOUDFLARE, { status: 403 }),
    TRIAL_OK(),
    new Response("", { status: 500 }),
  );
  const r = await unblockFetch("https://target.test/", { fetch: s.f });
  expect(r.via).toBe("direct");
  expect(r.status).toBe(403);
  expect(r.get_key_url).toBeTruthy();
});
