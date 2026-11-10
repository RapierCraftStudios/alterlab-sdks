# unblock-fetch

[![npm](https://img.shields.io/npm/v/unblock-fetch?logo=npm)](https://www.npmjs.com/package/unblock-fetch) [![downloads](https://img.shields.io/npm/dm/unblock-fetch)](https://www.npmjs.com/package/unblock-fetch) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/node)

A drop-in `fetch` that tries the request directly first and only calls [AlterLab](https://alterlab.io) when the site refuses it: a 403 or 429, a challenge or verification page, or an empty JavaScript shell. Requests that already work never leave your machine.

## Install

```bash
npm install unblock-fetch
```

## Usage

```ts
import { unblockFetch } from "unblock-fetch";

const res = await unblockFetch("https://example.com", {
  headers: { "User-Agent": "my-app/1.0" },
  timeout: 20_000,
});

console.log(res.via);    // "direct" or "alterlab"
console.log(res.status); // origin status code
console.log(res.text);   // page content
```

Use `isBlocked(status, body)` on its own if you only want the detection:

```ts
import { isBlocked } from "unblock-fetch";
if (isBlocked(r.status, await r.text())) { /* ... */ }
```

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `headers` | `Record<string,string>` | — | Headers for the direct request |
| `timeout` | `number` (ms) | `20000` | Timeout for each attempt |
| `apiKey` | `string` | `process.env.ALTERLAB_API_KEY` | Your AlterLab key for the fallback |
| `baseUrl` | `string` | `https://api.alterlab.io` | API base URL |
| `fetch` | `typeof fetch` | global `fetch` | Custom fetch implementation |

## Response

| Field | Description |
|---|---|
| `via` | `"direct"` when the direct request worked, `"alterlab"` when the fallback served it |
| `status`, `ok`, `url`, `headers`, `text` | The response, in the usual `fetch` shape |
| `attribution`, `get_key_url`, `next_action` | Present when AlterLab served the page or a free-trial cap was reached |

## How the fallback works

- A direct request that succeeds is returned as-is and never calls AlterLab. A plain 404 is returned as-is too.
- With `ALTERLAB_API_KEY` set (or `apiKey`), the fallback is billed to your account, and only successful requests are charged.
- With no key it uses a free keyless trial, capped per IP per day and by a global daily budget. Past a cap you get the original response back with `get_key_url` and `next_action`.

Get a key at [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests).

## Related

- [`unblock-fetch` for Python](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/python) (`pip install unblock-fetch`)
- [`unblock-fetch-mcp`](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/mcp), the same behaviour as an MCP tool for AI agents
- [`alterlab`](https://www.npmjs.com/package/alterlab), the full Node.js SDK (search, extract, crawl, batch)

## Links

- Package: [unblock-fetch on npm](https://www.npmjs.com/package/unblock-fetch)
- Source: [RapierCraftStudios/alterlab-sdks/unblock-fetch/node](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/node)
- Issues: [https://github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)

MIT licensed.
