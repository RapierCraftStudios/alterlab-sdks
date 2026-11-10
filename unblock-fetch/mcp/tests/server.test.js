const test = require("node:test");
const assert = require("node:assert");
const { handle } = require("../server");

const fake = async (url) => ({
  status: 200,
  via: "alterlab",
  text: "page:" + url,
  get_key_url: "https://alterlab.io/signup",
  attribution: { source: "unblock-fetch" },
});

test("lists the fetch tool", async () => {
  const r = await handle({ jsonrpc: "2.0", id: 1, method: "tools/list" }, fake);
  assert.deepStrictEqual(
    r.result.tools.map((t) => t.name),
    ["fetch"],
  );
});

test("fetch returns via and text", async () => {
  const r = await handle(
    {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: { name: "fetch", arguments: { url: "https://x.test" } },
    },
    fake,
  );
  const body = JSON.parse(r.result.content[0].text);
  assert.strictEqual(body.via, "alterlab");
  assert.strictEqual(body.text, "page:https://x.test");
});

test("missing url is an error and fetch errors are tool errors", async () => {
  const bad = await handle(
    { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "fetch", arguments: {} } },
    fake,
  );
  assert.strictEqual(bad.error.code, -32602);
  const boom = await handle(
    {
      jsonrpc: "2.0",
      id: 4,
      method: "tools/call",
      params: { name: "fetch", arguments: { url: "u" } },
    },
    async () => {
      throw new Error("net down");
    },
  );
  assert.strictEqual(boom.result.isError, true);
});

test("initialize and notifications", async () => {
  const r = await handle({ jsonrpc: "2.0", id: 5, method: "initialize", params: {} }, fake);
  assert.strictEqual(r.result.serverInfo.name, "unblock-fetch-mcp");
  assert.strictEqual(
    await handle({ jsonrpc: "2.0", method: "notifications/initialized" }, fake),
    null,
  );
});
