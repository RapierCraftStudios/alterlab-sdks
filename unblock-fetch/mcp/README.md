# unblock-fetch-mcp

[![npm](https://img.shields.io/npm/v/unblock-fetch-mcp?logo=npm)](https://www.npmjs.com/package/unblock-fetch-mcp) [![downloads](https://img.shields.io/npm/dm/unblock-fetch-mcp)](https://www.npmjs.com/package/unblock-fetch-mcp) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/mcp)

An [MCP](https://modelcontextprotocol.io) server with one tool, `fetch`. It fetches a URL directly and only retries through [AlterLab](https://alterlab.io) when the site refuses the request (a 403 or 429, a challenge or verification page, or an empty JavaScript shell). It works with Claude Desktop, Claude Code, Cursor, Windsurf and any other MCP client.

## Run

```bash
npx unblock-fetch-mcp
```

## Configure your client

Claude Desktop, Cursor, Windsurf and other clients take this JSON:

```json
{
  "mcpServers": {
    "unblock-fetch": {
      "command": "npx",
      "args": ["-y", "unblock-fetch-mcp"],
      "env": { "ALTERLAB_API_KEY": "sk_live_..." }
    }
  }
}
```

Claude Code:

```bash
claude mcp add unblock-fetch -- npx -y unblock-fetch-mcp
```

## The `fetch` tool

| Input | Type | Description |
|---|---|---|
| `url` | string, required | URL to fetch |
| `headers` | object | Headers for the direct request |

It returns the page text plus `via` (`direct` or `alterlab`), and `get_key_url` / `next_action` when relevant.

## Keys and limits

- `ALTERLAB_API_KEY` set: the fallback is billed to your account, and only successful requests are charged.
- No key: a free keyless trial, capped per IP per day and by a global daily budget. Past a cap the tool returns the original response with `get_key_url`.

Get a key at [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests). For the full tool set (search, extract, crawl, screenshots), use the [AlterLab MCP server](https://alterlab.io/docs/integrations/mcp).

## Links

- Package: [unblock-fetch-mcp on npm](https://www.npmjs.com/package/unblock-fetch-mcp)
- Built on: [unblock-fetch](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/node)
- Source: [RapierCraftStudios/alterlab-sdks/unblock-fetch/mcp](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/mcp)
- Issues: [https://github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)

MIT licensed.
