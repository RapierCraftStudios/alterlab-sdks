"""#36801: Python SDK search exposes engine/safe_search/rag and polls single and batch status."""

import json

import httpx
import pytest

from alterlab import AlterLab


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
async def test_search_sends_engine_safe_search_and_rag():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"results": []}), seen)
    await client.search(
        "q", engine="google", safe_search=True, scrape_results=True, formats=["rag"]
    )
    body = json.loads(seen[0].content)
    assert body["engine"] == "google"
    assert body["safe_search"] is True
    assert body["formats"] == ["rag"]


@pytest.mark.asyncio
async def test_search_defaults_to_unified_with_content_38613():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={}), seen)
    await client.search("q")
    body = json.loads(seen[0].content)
    assert "safe_search" not in body
    assert body["engine"] == "auto"
    assert body["scrape_results"] is True
    assert body["preset"] == "agent" and body["mode"] == "standard"
    assert seen[0].url.path == "/api/v1/search"


@pytest.mark.asyncio
async def test_search_defaults_can_be_turned_off_38613():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={}), seen)
    await client.search("q", scrape_results=False)
    await client.search("q", concise=False, wait=7)
    await client.search(queries=["a", "b"])
    await client.search("q", engine="duckduckgo")
    off, full, multi, ddg = (json.loads(r.content) for r in seen)
    assert off["scrape_results"] is False and "preset" not in off and "mode" not in off
    assert "preset" not in full and full["wait"] == 7 and "mode" not in full
    assert multi["scrape_results"] is False and multi["engine"] == "auto"
    assert ddg["engine"] == "duckduckgo" and ddg["scrape_results"] is False
    assert seen[3].url.path == "/api/v1/serp"


@pytest.mark.asyncio
async def test_search_unified_serp_sends_device_num_start():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"results": []}), seen)
    await client.search("q", engine="google", device="mobile", num=20, start=20)
    assert str(seen[0].url).endswith("/api/v1/serp")
    body = json.loads(seen[0].content)
    assert body["engine"] == "google"
    assert body["device"] == "mobile"
    assert body["num_results"] == 20
    assert body["start"] == 20


@pytest.mark.asyncio
async def test_search_unsupported_on_serp_keeps_legacy_alias():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={}), seen)
    await client.search("q", engine="google", scrape_results=True)
    await client.search("q", engine="google", domain="example.com")
    await client.search("q", engine="google", time_range="day")
    assert [r.url.path for r in seen] == ["/api/v1/search"] * 3


@pytest.mark.asyncio
async def test_batch_search_sends_engine_and_safe_search():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"batch_id": "b"}), seen)
    await client.batch_search(["a"], engine="bing", safe_search=False, formats=["rag"])
    body = json.loads(seen[0].content)
    assert body["engine"] == "bing"
    assert body["safe_search"] is False
    assert body["formats"] == ["rag"]


@pytest.mark.asyncio
async def test_polling_helpers_hit_status_endpoints():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"status": "completed"}), seen)
    assert (await client.get_search("s1"))["status"] == "completed"
    assert (await client.get_batch_search("b1"))["status"] == "completed"
    assert [r.url.path for r in seen] == [
        "/api/v1/search/s1",
        "/api/v1/search/batch/b1",
    ]
    assert all(r.method == "GET" for r in seen)


@pytest.mark.asyncio
async def test_search_queries_posts_to_search_route_and_requires_exactly_one():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"results": []}), seen)
    await client.search(queries=["a", "b"])
    body = json.loads(seen[0].content)
    assert body["queries"] == ["a", "b"]
    assert "query" not in body
    assert str(seen[0].url).endswith("/api/v1/search")
    with pytest.raises(ValueError):
        await client.search("q", queries=["a"])
    with pytest.raises(ValueError):
        await client.search()


@pytest.mark.asyncio
async def test_search_unified_engine_auto_goes_to_search_endpoint_38613():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"results": []}), seen)
    await client.search("q", engine="auto")
    assert seen[0].url.path == "/api/v1/search"
    assert json.loads(seen[0].content)["engine"] == "auto"
