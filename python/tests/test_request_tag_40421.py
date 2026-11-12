"""Coverage for #40421: request ``tag`` is forwarded by every tag-aware method."""

import json

import httpx
import pytest

from alterlab import AlterLab

ITEMS = [{"url": "https://example.com/a", "mode": "html"}]

CALLS = {
    "scrape": lambda c, **kw: c.scrape("https://example.com", **kw),
    "batch_scrape": lambda c, **kw: c.batch_scrape(ITEMS, **kw),
    "crawl": lambda c, **kw: c.crawl("https://example.com", **kw),
    "search": lambda c, **kw: c.search("alterlab", **kw),
    "batch_search": lambda c, **kw: c.batch_search(["a", "b"], **kw),
    "map": lambda c, **kw: c.map("https://example.com", **kw),
    "extract": lambda c, **kw: c.extract("<p>hi</p>", **kw),
}


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "ok", "tag": captured[-1].get("tag")}
        )

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("method", sorted(CALLS))
async def test_tag_sent_when_set(method):
    captured = []
    await CALLS[method](_make_client(captured), tag="q3-sweep")
    assert captured[0]["tag"] == "q3-sweep"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", sorted(CALLS))
async def test_tag_omitted_when_unset(method):
    captured = []
    await CALLS[method](_make_client(captured))
    assert "tag" not in captured[0]
