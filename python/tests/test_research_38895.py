"""#38895: Python SDK research methods map onto /api/v1/research."""

import json

import httpx
import pytest

from alterlab import AlterLab, AlterLabTimeoutError


def _client(handler, seen):
    client = AlterLab(api_key="sk_test_dummy")

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(wrapped)
    )
    return client


@pytest.mark.asyncio
async def test_research_posts_query_and_options_and_drops_none():
    seen = []
    client = _client(
        lambda r: httpx.Response(202, json={"id": "j1", "status": "queued"}), seen
    )
    job = await client.research("q", effort="deep", max_cost_microcents=5, model=None)
    assert job["id"] == "j1"
    assert seen[0].method == "POST" and seen[0].url.path == "/api/v1/research"
    assert json.loads(seen[0].content) == {
        "query": "q",
        "effort": "deep",
        "max_cost_microcents": 5,
    }


@pytest.mark.asyncio
async def test_research_rejects_unknown_option():
    client = _client(lambda r: httpx.Response(202, json={}), [])
    with pytest.raises(ValueError, match="bogus"):
        await client.research("q", bogus=1)


@pytest.mark.asyncio
async def test_wait_polls_until_settled():
    seen = []
    states = iter(["queued", "running", "completed"])
    client = _client(
        lambda r: httpx.Response(200, json={"id": "j1", "status": next(states)}), seen
    )
    job = await client.wait_for_research("j1", poll_interval=0.001)
    assert job["status"] == "completed"
    assert [r.url.path for r in seen] == ["/api/v1/research/j1"] * 3


@pytest.mark.asyncio
async def test_wait_times_out_and_returns_on_awaiting_approval():
    client = _client(lambda r: httpx.Response(200, json={"status": "running"}), [])
    with pytest.raises(AlterLabTimeoutError):
        await client.wait_for_research("j1", poll_interval=0.001, timeout=0.005)
    client = _client(
        lambda r: httpx.Response(200, json={"status": "awaiting_approval"}), []
    )
    assert (await client.wait_for_research("j1"))["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_cancel_plan_and_approve_endpoints():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"ok": True}), seen)
    await client.cancel_research("j1")
    await client.get_research_plan("j1")
    await client.update_research_plan("j1", {"steps": []})
    await client.approve_research("j1")
    await client.approve_research("j1", {"steps": ["a"]})
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/api/v1/research/j1/cancel"),
        ("GET", "/api/v1/research/j1/plan"),
        ("PUT", "/api/v1/research/j1/plan"),
        ("POST", "/api/v1/research/j1/approve"),
        ("POST", "/api/v1/research/j1/approve"),
    ]
    assert json.loads(seen[2].content) == {"plan": {"steps": []}}
    assert seen[3].content == b""
    assert json.loads(seen[4].content) == {"plan": {"steps": ["a"]}}


@pytest.mark.asyncio
async def test_events_parse_sse_and_send_last_event_id():
    seen = []
    body = (
        'id: 1\nevent: status\ndata: {"status":"running"}\n\n'
        ": keepalive\n\n"
        'id: 2\nevent: research.completed\ndata: {"status":"completed"}\n\n'
    )
    client = _client(lambda r: httpx.Response(200, text=body), seen)
    events = await client.research_events("j1", last_event_id="0")
    assert seen[0].headers["Last-Event-ID"] == "0"
    assert [(e["id"], e["event"], e["data"]["status"]) for e in events] == [
        ("1", "status", "running"),
        ("2", "research.completed", "completed"),
    ]


def test_sync_client_exposes_research_methods():
    from alterlab import AlterLabSync

    for name in (
        "research",
        "get_research",
        "cancel_research",
        "wait_for_research",
        "research_events",
        "get_research_plan",
        "update_research_plan",
        "approve_research",
    ):
        assert callable(getattr(AlterLabSync, name))
