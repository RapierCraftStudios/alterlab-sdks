"""Stdio MCP server (``alterlab mcp``) and ``alterlab skill install`` (#38951)."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .cli_data import client_from_env

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "alterlab", "version": "1.0.0"}

SKILL_MD = """---
name: alterlab
description: Fetch, scrape, crawl and search the web through the alterlab CLI when plain fetches are blocked.
---

Use the `alterlab` CLI. Output is NDJSON (or markdown) on stdout, cost on stderr.

- `alterlab scrape <url> -f md` page as markdown; add `--render` for JavaScript pages
- `alterlab crawl <url> --max 50`, `alterlab map <url>`, `alterlab search "<q>" --content`
- `alterlab extract <url> --profile product`
- Preview spend with `--estimate`; cap it with `--max-cost 0.05`
- No account needed: `alterlab detect <url>`, `alterlab doctor <url>`, `alterlab md <file|url>`
- First run: `alterlab login --email you@example.com` (a human approves in the browser)
"""


def load_tool_definitions() -> List[Dict[str, Any]]:
    path = Path(__file__).parent / "data" / "tool_definitions.json"
    return json.loads(path.read_text())["tools"]


def _call_scrape(client, a):
    return client.scrape(a["url"], formats=a.get("formats") or ["markdown"])


HANDLERS: Dict[str, Callable[[Any, Dict[str, Any]], Any]] = {
    "alterlab_scrape": _call_scrape,
    "alterlab_search": lambda c, a: c.search(a["query"]),
    "alterlab_map": lambda c, a: c.map(a["url"]),
    "alterlab_crawl": lambda c, a: c.crawl(a["url"]),
    "alterlab_estimate_cost": lambda c, a: c.estimate_cost(a["url"]),
}


def _public_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: tool[k]
        for k in ("name", "title", "description", "inputSchema", "annotations")
        if k in tool
    }


def handle(
    message: Dict[str, Any],
    get_client: Callable[[], Any] = client_from_env,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    tools = tools if tools is not None else load_tool_definitions()
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None  # notification

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [_public_tool(t) for t in tools]})
    if method == "tools/call":
        params = message.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in tools}:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32602, "message": f"unknown tool {name}"},
            }
        handler = HANDLERS.get(name)
        if handler is None:
            text, err = f"{name} is only available on the hosted MCP server", True
        else:
            try:
                with get_client() as client:
                    text, err = json.dumps(handler(client, args), default=str), False
            except Exception as exc:  # surfaced to the agent, not a protocol error
                text, err = f"{type(exc).__name__}: {exc}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": err})
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0


def skill_dir(agent: str = "claude") -> Path:
    base = os.environ.get("ALTERLAB_SKILLS_DIR")
    if base:
        return Path(base)
    home = Path.home()
    return {
        "claude": home / ".claude" / "skills",
        "codex": home / ".codex" / "skills",
        "agents": home / ".agents" / "skills",
    }.get(agent, home / ".claude" / "skills")


def skill_install(agent: str = "claude") -> Path:
    target = skill_dir(agent) / "alterlab"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(SKILL_MD)
    return target
