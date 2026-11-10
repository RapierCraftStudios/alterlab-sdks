"""Coverage for #39016: ``extraction_selectors`` reaches the POST body for
scrape, estimate_cost, extract and batch_scrape, and is omitted when unset.
"""

import json

import httpx
import pytest

from alterlab import AlterLab

SELECTORS = {
    "price": {"css": ".price", "attr": "content"},
    "links": {"xpath": "//a", "attr": "href", "multiple": True},
}


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"status": "succeeded", "job_id": "job_1", "batch_id": "b"}
        )

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


def _body(captured):
    return json.loads(captured[-1].content)


@pytest.mark.asyncio
async def test_scrape_sends_selectors():
    captured = []
    client = _make_client(captured)
    await client.scrape("https://example.com", extraction_selectors=SELECTORS)
    assert _body(captured)["extraction_selectors"] == SELECTORS


@pytest.mark.asyncio
async def test_estimate_cost_sends_selectors():
    captured = []
    client = _make_client(captured)
    await client.estimate_cost("https://example.com", extraction_selectors=SELECTORS)
    assert captured[-1].url.path == "/api/v1/scrape/estimate"
    assert _body(captured)["extraction_selectors"] == SELECTORS


@pytest.mark.asyncio
async def test_extract_sends_selectors():
    captured = []
    client = _make_client(captured)
    await client.extract("<p class='price'>1</p>", extraction_selectors=SELECTORS)
    assert _body(captured)["extraction_selectors"] == SELECTORS


@pytest.mark.asyncio
async def test_selectors_omitted_when_unset():
    captured = []
    client = _make_client(captured)
    await client.scrape("https://example.com")
    assert "extraction_selectors" not in _body(captured)
    await client.estimate_cost("https://example.com")
    assert "extraction_selectors" not in _body(captured)
    await client.extract("<p>x</p>")
    assert "extraction_selectors" not in _body(captured)


@pytest.mark.asyncio
async def test_batch_scrape_passes_item_selectors():
    captured = []
    client = _make_client(captured)
    items = [{"url": "https://example.com/a", "extraction_selectors": SELECTORS}]
    await client.batch_scrape(items)
    assert _body(captured)["urls"][0]["extraction_selectors"] == SELECTORS
