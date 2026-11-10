"""#40286: every MCP tool has a Python and a Node SDK method, or a reasoned allowlist entry."""

import json
import re
from pathlib import Path

import httpx
import pytest

from alterlab import AlterLab, AlterLabSync, _namespaces

ROOT = Path(__file__).resolve().parents[3]
TOOLS = json.loads((ROOT / "shared/mcp_tools/tool_definitions.json").read_text())[
    "tools"
]
NODE_SRC = "".join(
    (ROOT / "sdk/node/src" / name).read_text()
    for name in ("index.ts", "mcpNamespaces.ts")
)

# tool -> (python "attr" or "namespace.attr", node "attr" or "namespace.attr")
SDK_METHODS = {
    "alterlab_scrape": ("scrape", "scrape"),
    "alterlab_screenshot": ("screenshot", "screenshot"),
    "alterlab_extract": ("extract", "extract"),
    "alterlab_batch": ("batch_scrape", "batchScrape"),
    "alterlab_batch_scrape": ("batch_scrape", "batchScrape"),
    "alterlab_crawl": ("crawl", "crawl"),
    "alterlab_map": ("map", "map"),
    "alterlab_search": ("search", "search"),
    "alterlab_serp": ("serp", "serp"),
    "alterlab_research": ("research", "research"),
    "alterlab_estimate_cost": ("estimate_cost", "estimateCost"),
    "alterlab_job": ("get_job_status", "getJobStatus"),
    "alterlab_feedback": ("feedback", "feedback"),
    "alterlab_support_ticket": ("support.ticket", "support.ticket"),
    "alterlab_balance": ("account.balance", "account.balance"),
    "alterlab_pricing": ("pricing", "pricing"),
    "alterlab_news": ("news", "news"),
    "alterlab_keyword_ideas": ("keyword_ideas", "keywordIdeas"),
    "alterlab_ai_visibility": ("ai_visibility", "aiVisibility"),
    "alterlab_monitor": ("monitors.create", "monitors.create"),
    "alterlab_schedule": ("schedules.create", "schedules.create"),
    "alterlab_workflow_run": ("workflows.run", "workflows.run"),
    "alterlab_store_search": ("store.search", "store.search"),
    "alterlab_store_get": ("store.get", "store.get"),
    "alterlab_store_quote": ("store.quote", "store.quote"),
    "alterlab_store_run": ("store.run", "store.run"),
    "alterlab_feed_list": ("feeds.list", "feeds.list"),
    "alterlab_feed_create": ("feeds.create", "feeds.create"),
    "alterlab_feed_update": ("feeds.update", "feeds.update"),
    "alterlab_feed_delete": ("feeds.delete", "feeds.delete"),
    "alterlab_feed_deltas": ("feeds.deltas", "feeds.deltas"),
}

_HANDS = "Hands agent-control surface: reach it with hands_request(); MCP/agent UX"
_ALIAS = "MCP alias of a tool that already has an SDK method"
ALLOWLIST = {
    "read_alterlab_page": _ALIAS + " (scrape)",
    "search_alterlab": _ALIAS + " (search)",
    "alterlab_connect": "MCP connection bootstrap; meaningless once you hold an API key",
    "alterlab_create_account": "Account creation for keyless agents; MCP-only onboarding",
    "alterlab_create_api_key": "Key minting for keyless agents; MCP-only onboarding",
    "alterlab_request_credential": "Interactive human credential hand-off; MCP/agent UX",
    "alterlab_content_check": "MCP-side content-policy helper for agents",
    "alterlab_policy_evaluate": "MCP-side policy helper for agents",
    "alterlab_sessions": "Hands browser sessions: reach it with hands_request()",
    "alterlab_facts": _HANDS,
    "alterlab_routes": _HANDS,
    "alterlab_requirements": _HANDS,
    "alterlab_hands_access": _HANDS,
    "alterlab_hands_answer": _HANDS,
    "alterlab_hands_conversations": _HANDS,
    "alterlab_hands_pending": _HANDS,
    "alterlab_hands_run": _HANDS,
    "alterlab_hands_share": _HANDS,
    "alterlab_hands_triggers": _HANDS,
    "alterlab_task_act": _HANDS,
    "alterlab_task_answer": _HANDS,
    "alterlab_task_control": _HANDS,
    "alterlab_task_observe": _HANDS,
    "alterlab_task_schema": _HANDS,
    "alterlab_task_start": _HANDS,
    "alterlab_task_status": _HANDS,
    "alterlab_task_vision_act": _HANDS,
    "alterlab_task_vision_capture": _HANDS,
    "alterlab_run_approve": "Run lifecycle driven through the alterlab run CLI / MCP streaming",
    "alterlab_run_cancel": "Run lifecycle driven through the alterlab run CLI / MCP streaming",
    "alterlab_run_create": "Run lifecycle driven through the alterlab run CLI / MCP streaming",
    "alterlab_run_result": "Run lifecycle driven through the alterlab run CLI / MCP streaming",
    "alterlab_run_stream": "Streaming MCP transport; not a request/response method",
    "alterlab_listing_draft_create": "Publisher workflow handled in the dashboard / MCP",
    "alterlab_listing_draft_test": "Publisher workflow handled in the dashboard / MCP",
    "alterlab_listing_publish": "Publisher workflow handled in the dashboard / MCP",
}


def _python_has(path):
    target = AlterLab
    parts = path.split(".")
    if len(parts) == 2:
        target = {
            "account": _namespaces.AccountNamespace,
            "support": _namespaces.SupportNamespace,
            "jobs": _namespaces.JobsNamespace,
            "monitors": _namespaces.MonitorsNamespace,
            "schedules": _namespaces.SchedulesNamespace,
            "store": _namespaces.StoreNamespace,
            "feeds": _namespaces.FeedsNamespace,
            "workflows": _namespaces.WorkflowsNamespace,
        }[parts[0]]
    return callable(getattr(target, parts[-1], None))


def _node_has(path):
    name = path.split(".")[-1]
    return re.search(
        rf"^\s*(?:public\s+|protected\s+)?(?:async\s+)?{name}\s*[(<]", NODE_SRC, re.M
    )


def test_every_mcp_tool_has_sdk_methods_or_allowlist_reason():
    names = {t["name"] for t in TOOLS}
    unmapped = names - SDK_METHODS.keys() - ALLOWLIST.keys()
    assert (
        not unmapped
    ), f"MCP tools with no SDK method and no allowlist reason: {sorted(unmapped)}"
    stale = (SDK_METHODS.keys() | ALLOWLIST.keys()) - names
    assert not stale, f"entries for tools that no longer exist: {sorted(stale)}"
    assert not SDK_METHODS.keys() & ALLOWLIST.keys()
    assert all(reason.strip() for reason in ALLOWLIST.values())


@pytest.mark.parametrize("tool", sorted(SDK_METHODS))
def test_mapped_methods_exist_in_python_and_node(tool):
    py, node = SDK_METHODS[tool]
    assert _python_has(py), f"{tool}: Python method {py} missing"
    assert _node_has(node), f"{tool}: Node method {node} missing"


def _client(seen, payload=None, status=200, text=None):
    def handler(request):
        seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload or {"ok": True})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_support_ticket_and_report_post_expected_bodies():
    seen = []
    client = _client(seen)
    await client.support.ticket("Broken", "details", job_id="j1")
    await client.jobs.report("j1", "blocked", description="d")
    await client.support_ticket("Alias", "b")
    assert [r.url.path for r in seen] == [
        "/api/v1/agent/support-ticket",
        "/api/v1/feedback/scrape",
        "/api/v1/agent/support-ticket",
    ]
    assert json.loads(seen[0].content) == {
        "subject": "Broken",
        "body": "details",
        "on_behalf_of_user": True,
        "job_id": "j1",
    }
    assert json.loads(seen[1].content) == {
        "job_id": "j1",
        "issue_type": "blocked",
        "description": "d",
    }
    with pytest.raises(ValueError):
        await client.jobs.report("j1", "nonsense")


@pytest.mark.asyncio
async def test_read_methods_use_expected_routes_and_quote_ids():
    seen = []
    client = _client(seen)
    await client.account.balance()
    await client.pricing()
    await client.news(q="ai", limit=3)
    await client.store.get("a/b")
    await client.feeds.deltas("f1", page=2)
    await client.ai_visibility("status", run_id="r1")
    paths = [(r.method, r.url.raw_path.decode()) for r in seen]
    assert paths == [
        ("GET", "/api/v1/billing/balance"),
        ("GET", "/api/v1/pricing"),
        ("GET", "/api/v1/news?q=ai&limit=3"),
        ("GET", "/api/v1/listings/a%2Fb"),
        ("GET", "/api/v1/listings/feeds/f1/deltas?page=2"),
        ("GET", "/api/v1/ai-visibility/runs/r1"),
    ]


@pytest.mark.asyncio
async def test_unexpected_response_hook_is_opt_in_and_never_files_anything():
    seen, events = [], []
    client = _client(seen, text="<html>oops</html>")
    await client.pricing()
    assert len(seen) == 1  # no hook: nothing else is sent
    client.on_unexpected_response = events.append
    await client.pricing()
    assert len(seen) == 2  # hook only notifies; no feedback/ticket request
    assert events == [
        {
            "method": "GET",
            "path": "/api/v1/pricing",
            "status_code": 200,
            "reason": "body is not JSON",
        }
    ]


def test_sync_client_exposes_namespaces():
    client = AlterLabSync(api_key="sk_test_dummy")
    assert callable(client.support.ticket)
    assert callable(client.jobs.report)
    assert callable(client.pricing)


OPENAPI = ROOT / "web/public/openapi.json"


@pytest.mark.skipif(not OPENAPI.exists(), reason="OpenAPI spec not in this checkout")
@pytest.mark.asyncio
async def test_every_wrapper_route_exists_in_the_openapi_spec():
    paths = json.loads(OPENAPI.read_text())["paths"]
    templates = [
        (re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", p) + "$"), set(ops))
        for p, ops in paths.items()
    ]
    seen = []
    c = _client(seen)
    await c.account.balance()
    await c.account.usage()
    await c.support.ticket("s", "b")
    await c.jobs.report("j", "blocked")
    await c.jobs.explain("j")
    for ns in (c.monitors, c.schedules):
        await ns.list()
        await ns.create(name="n")
    await c.monitors.delete("m")
    await c.store.search()
    await c.store.get("s")
    await c.store.quote("s")
    await c.store.run("s")
    await c.feeds.list("s")
    await c.feeds.create("s")
    await c.feeds.update("s", "f")
    await c.feeds.delete("s", "f")
    await c.feeds.deltas("f")
    await c.workflows.run("w")
    await c.pricing()
    await c.news()
    await c.keyword_ideas(keyword="k")
    await c.serp("q")
    await c.screenshot("https://example.com")
    for action in ("check", "quote"):
        await c.ai_visibility(action)
    for action in ("status", "results"):
        await c.ai_visibility(action, run_id="r")
    missing = [
        f"{r.method} {r.url.path}"
        for r in seen
        if not any(
            rx.match(r.url.raw_path.decode().split("?")[0]) and r.method.lower() in ops
            for rx, ops in templates
        )
    ]
    assert not missing, f"wrapper routes absent from the OpenAPI spec: {missing}"
