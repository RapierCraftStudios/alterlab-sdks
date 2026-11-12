"""Coverage for #40428: ``batch_scrape`` and ``crawl`` forward ``approval_id``."""

import json

import httpx
import pytest

from alterlab import AlterLab

ITEMS = [{"url": "https://example.com/a", "mode": "html"}]


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"status": "pending_approval", "approval_id": "apr_1"})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_batch_scrape_sends_approval_id_when_set():
    captured = []
    result = await _make_client(captured).batch_scrape(ITEMS, approval_id="apr_1")
    assert captured[0]["approval_id"] == "apr_1"
    assert result["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_crawl_sends_approval_id_when_set():
    captured = []
    await _make_client(captured).crawl("https://example.com", approval_id="apr_1")
    assert captured[0]["approval_id"] == "apr_1"


@pytest.mark.asyncio
async def test_approval_id_omitted_by_default():
    captured = []
    client = _make_client(captured)
    await client.batch_scrape(ITEMS)
    await client.crawl("https://example.com")
    assert all("approval_id" not in body for body in captured)
