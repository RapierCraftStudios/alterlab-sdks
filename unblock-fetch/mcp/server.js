#!/usr/bin/env node
// Minimal MCP server (JSON-RPC 2.0 over stdio, newline-delimited) exposing one tool: `fetch`.
"use strict";

const readline = require("node:readline");

const TOOL = {
  name: "fetch",
  description:
    "Fetch a URL directly; only if that is blocked (403/429, challenge, CAPTCHA, empty JS shell) " +
    "retry through AlterLab. Returns the page text, `via` (direct|alterlab) and, when relevant, " +
    "get_key_url and next_action.",
  inputSchema: {
    type: "object",
    properties: {
      url: { type: "string", description: "URL to fetch" },
      headers: { type: "object", additionalProperties: { type: "string" } },
    },
    required: ["url"],
  },
};

async function callTool(params, unblockFetch) {
  if (!params || params.name !== "fetch") throw { code: -32602, message: "unknown tool" };
  const args = params.arguments || {};
  if (typeof args.url !== "string" || !args.url) throw { code: -32602, message: "url is required" };
  try {
    const r = await unblockFetch(args.url, { headers: args.headers });
    const { status, via, attribution, get_key_url, next_action, text } = r;
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ status, via, attribution, get_key_url, next_action, text }),
        },
      ],
    };
  } catch (e) {
    return { isError: true, content: [{ type: "text", text: String((e && e.message) || e) }] };
  }
}

async function handle(msg, unblockFetch) {
  const { id, method, params } = msg;
  if (id === undefined) return null; // notification
  try {
    if (method === "initialize") {
      return {
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: (params && params.protocolVersion) || "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: { name: "unblock-fetch-mcp", version: "0.1.1" },
        },
      };
    }
    if (method === "ping") return { jsonrpc: "2.0", id, result: {} };
    if (method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: [TOOL] } };
    if (method === "tools/call")
      return { jsonrpc: "2.0", id, result: await callTool(params, unblockFetch) };
    return { jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } };
  } catch (e) {
    return {
      jsonrpc: "2.0",
      id,
      error: { code: e.code || -32603, message: e.message || "internal error" },
    };
  }
}

function serve(unblockFetch) {
  const rl = readline.createInterface({ input: process.stdin });
  rl.on("line", async (line) => {
    if (!line.trim()) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      process.stdout.write(
        JSON.stringify({
          jsonrpc: "2.0",
          id: null,
          error: { code: -32700, message: "parse error" },
        }) + "\n",
      );
      return;
    }
    const out = await handle(msg, unblockFetch);
    if (out) process.stdout.write(JSON.stringify(out) + "\n");
  });
}

module.exports = { handle, TOOL };

if (require.main === module) serve(require("unblock-fetch").unblockFetch);
