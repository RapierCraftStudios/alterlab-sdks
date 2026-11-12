"""Coverage for #40351: approval exposure in the Python SDK and the shared MCP tools."""

import json
from pathlib import Path

import httpx
import pytest

from alterlab import AlterLab

ITEMS = [{"url": "https://example.com/a", "mode": "html"}]
SHARED = Path(__file__).resolve().parents[3] / "shared/mcp_tools/tool_definitions.json"


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append((request.method, request.url.raw_path.decode(), body))
        return httpx.Response(200, json={"status": "approved"})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_batch_and_crawl_send_approval_id():
    captured = []
    client = _make_client(captured)
    await client.batch_scrape(ITEMS, approval_id="apr_1")
    await client.crawl("https://example.com", approval_id="apr_2")
    assert captured[0][2]["approval_id"] == "apr_1"
    assert captured[1][2]["approval_id"] == "apr_2"


@pytest.mark.asyncio
async def test_approval_id_omitted_by_default():
    captured = []
    client = _make_client(captured)
    await client.batch_scrape(ITEMS)
    await client.crawl("https://example.com")
    assert all("approval_id" not in c[2] for c in captured)


@pytest.mark.asyncio
async def test_get_approval_and_tag_threshold_routes():
    captured = []
    client = _make_client(captured)
    await client.get_approval("apr 1")
    await client.get_tag_approval("nightly")
    await client.set_tag_approval("nightly", 5.0)
    assert captured == [
        ("GET", "/api/v1/approvals/apr%201", None),
        ("GET", "/api/v1/usage-tags/nightly/approval", None),
        ("PUT", "/api/v1/usage-tags/nightly/approval", {"approval_above_usd": 5.0}),
    ]


def test_mcp_tools_expose_dry_run_approval_and_resume():
    tools = {t["name"]: t for t in json.loads(SHARED.read_text())["tools"]}
    for name in ("alterlab_batch", "alterlab_crawl"):
        props = tools[name]["inputSchema"]["properties"]
        assert "dry_run" in props and "approval_id" in props
    assert tools["alterlab_approval"]["inputSchema"]["required"] == ["approval_id"]
    assert tools["alterlab_batch_resume"]["inputSchema"]["required"] == ["batch_id"]
