"""Coverage for #40403: ``batch_scrape`` and ``crawl`` forward ``dry_run``."""

import json

import httpx
import pytest

from alterlab import AlterLab

ITEMS = [{"url": "https://example.com/a", "mode": "html"}]


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"dry_run": True, "status": "dry_run"})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_batch_scrape_sends_dry_run_when_set():
    captured = []
    result = await _make_client(captured).batch_scrape(ITEMS, dry_run=True)
    assert captured[0]["dry_run"] is True
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_crawl_sends_dry_run_when_set():
    captured = []
    await _make_client(captured).crawl("https://example.com", dry_run=True)
    assert captured[0]["dry_run"] is True


@pytest.mark.asyncio
async def test_dry_run_omitted_by_default():
    captured = []
    client = _make_client(captured)
    await client.batch_scrape(ITEMS)
    await client.crawl("https://example.com")
    assert all("dry_run" not in body for body in captured)
