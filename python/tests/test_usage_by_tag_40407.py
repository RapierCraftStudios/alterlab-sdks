"""Coverage for #40407: crawl_and_wait tag, usage tag filters and tag budget helpers."""

import json

import httpx
import pytest

from alterlab import AlterLab


def _make_client(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/crawl":
            return httpx.Response(200, json={"crawl_id": "c1"})
        if request.url.path.startswith("/api/v1/crawl/"):
            return httpx.Response(200, json={"status": "completed", "crawl_id": "c1"})
        return httpx.Response(200, json={"ok": True})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_crawl_and_wait_forwards_tag():
    seen = []
    await _make_client(seen).crawl_and_wait("https://example.com", tag="sweep")
    assert json.loads(seen[0].content)["tag"] == "sweep"


@pytest.mark.asyncio
async def test_crawl_and_wait_omits_tag_by_default():
    seen = []
    await _make_client(seen).crawl_and_wait("https://example.com")
    assert "tag" not in json.loads(seen[0].content)


@pytest.mark.asyncio
async def test_get_usage_sends_tag_and_since_only_when_set():
    seen = []
    client = _make_client(seen)
    await client.get_usage()
    await client.get_usage(tag="sweep", since="2026-01-01T00:00:00Z")
    assert dict(seen[0].url.params) == {}
    assert dict(seen[1].url.params) == {"tag": "sweep", "since": "2026-01-01T00:00:00Z"}


@pytest.mark.asyncio
async def test_account_usage_by_tag_routes():
    seen = []
    client = _make_client(seen)
    await client.account.usage_by_tag(since="2026-01-01")
    await client.account.usage_by_tag(tag="sweep")
    assert seen[0].url.path == "/api/v1/usage/tags"
    assert seen[0].url.params["since"] == "2026-01-01"
    assert seen[1].url.path == "/api/v1/usage"
    assert seen[1].url.params["tag"] == "sweep"


@pytest.mark.asyncio
async def test_account_set_tag_budget_puts_cap():
    seen = []
    client = _make_client(seen)
    await client.account.set_tag_budget(
        "sweep", 16.0, expires_at="2026-12-01T00:00:00Z"
    )
    await client.account.set_tag_budget("sweep", 5)
    assert seen[0].method == "PUT" and seen[0].url.path == "/api/v1/usage/tags/sweep"
    assert json.loads(seen[0].content) == {
        "max_spend_usd": 16.0,
        "expires_at": "2026-12-01T00:00:00Z",
    }
    assert json.loads(seen[1].content) == {"max_spend_usd": 5}
