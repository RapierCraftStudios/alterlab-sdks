"""Coverage for #35843: ``batch_scrape`` must send the API ``BatchRequest``
field ``urls`` (not ``requests``), which previously made every call return 422.
"""

import json

import httpx
import pytest

from alterlab import AlterLab, AlterLabSync

BATCH_RESPONSE = {
    "batch_id": "batch_123",
    "total_urls": 2,
    "status": "processing",
    "estimated_credits": 2,
    "job_ids": ["job_a", "job_b"],
    "accepted_urls": 2,
    "rejected_urls": 0,
}

ITEMS = [
    {"url": "https://example.com/a", "mode": "html"},
    {"url": "https://example.com/b", "mode": "js"},
]


def _capturing_transport(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202, json=BATCH_RESPONSE)

    return httpx.MockTransport(handler)


def _make_client(captured) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=_capturing_transport(captured)
    )
    return client


@pytest.mark.asyncio
async def test_batch_scrape_sends_urls_field():
    captured = []
    client = _make_client(captured)

    result = await client.batch_scrape(ITEMS)

    assert result == BATCH_RESPONSE
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/batch"
    body = json.loads(request.content)
    assert body == {"urls": ITEMS}
    assert "requests" not in body


@pytest.mark.asyncio
async def test_batch_scrape_includes_webhook_url_only_when_given():
    captured = []
    client = _make_client(captured)

    await client.batch_scrape(ITEMS, webhook_url="https://myapp.com/webhook")

    body = json.loads(captured[0].content)
    assert body == {"urls": ITEMS, "webhook_url": "https://myapp.com/webhook"}


@pytest.mark.asyncio
async def test_batch_scrape_sends_max_in_flight_per_domain_only_when_given():
    captured = []
    client = _make_client(captured)

    await client.batch_scrape(ITEMS, max_in_flight_per_domain=3)
    await client.batch_scrape(ITEMS)

    assert json.loads(captured[0].content) == {
        "urls": ITEMS,
        "max_in_flight_per_domain": 3,
    }
    assert "max_in_flight_per_domain" not in json.loads(captured[1].content)


def test_sync_batch_scrape_sends_urls_field():
    captured = []
    sync_client = AlterLabSync(api_key="sk_test_dummy")
    sync_client._client.client = httpx.AsyncClient(
        base_url=sync_client._client.base_url,
        transport=_capturing_transport(captured),
    )

    result = sync_client.batch_scrape(ITEMS)

    assert result == BATCH_RESPONSE
    body = json.loads(captured[0].content)
    assert body == {"urls": ITEMS}
    assert "requests" not in body
