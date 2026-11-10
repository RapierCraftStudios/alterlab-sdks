"""Coverage for #38991: ``response`` on scrape and ``sync`` on search are sent only when set."""

import json

import httpx
import pytest

from alterlab import AlterLab


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_scrape_sends_response_minimal_and_returns_body_untouched():
    seen = {}
    minimal = {"content": "hi", "status_code": 200, "url": "https://e.com"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=minimal)

    result = await _client(handler).scrape("https://e.com", response="minimal")
    assert seen["response"] == "minimal"
    assert result == minimal


@pytest.mark.asyncio
async def test_scrape_omits_response_by_default():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"content": "hi", "status_code": 200})

    await _client(handler).scrape("https://e.com")
    assert "response" not in seen


@pytest.mark.asyncio
async def test_search_sync_sent_only_when_true_and_routes_to_search():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"search_id": "s", "query": "q", "results": []})

    client = _client(handler)
    await client.search("q", scrape_results=True, sync=True)
    await client.search("q", scrape_results=True)
    assert calls[0][0] == "/api/v1/search" and calls[0][1]["sync"] is True
    assert calls[1][0] == "/api/v1/search" and "sync" not in calls[1][1]
