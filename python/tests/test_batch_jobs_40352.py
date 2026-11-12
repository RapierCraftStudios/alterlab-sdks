"""Coverage for #40352: ``resubmit_rejected`` resends only rejected indices."""

import json

import httpx
import pytest

from alterlab import AlterLab

ITEMS = [{"url": f"https://example.com/{i}"} for i in range(4)]
RESPONSE = {
    "batch_id": "batch_1",
    "total_urls": 4,
    "status": "processing",
    "estimated_credits": 3,
    "job_ids": ["a", "c", "d"],
    "jobs": [
        {"index": 0, "url": ITEMS[0]["url"], "status": "accepted", "job_id": "a", "rejected": None},
        {
            "index": 1,
            "url": ITEMS[1]["url"],
            "status": "rejected",
            "job_id": None,
            "rejected": {"scope": "global_concurrent", "reason": "x", "retry_after_seconds": 5},
        },
        {"index": 2, "url": ITEMS[2]["url"], "status": "accepted", "job_id": "c", "rejected": None},
        {"index": 3, "url": ITEMS[3]["url"], "status": "accepted", "job_id": "d", "rejected": None},
    ],
}


def _client(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202, json=RESPONSE)

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_resubmit_rejected_sends_only_rejected_items():
    captured = []
    client = _client(captured)

    await client.resubmit_rejected(ITEMS, RESPONSE)

    assert len(captured) == 1
    assert json.loads(captured[0].content) == {"urls": [ITEMS[1]]}


@pytest.mark.asyncio
async def test_resubmit_rejected_is_noop_when_nothing_rejected():
    captured = []
    client = _client(captured)
    accepted_only = {**RESPONSE, "jobs": [j for j in RESPONSE["jobs"] if j["status"] == "accepted"]}

    assert await client.resubmit_rejected(ITEMS, accepted_only) is None
    assert captured == []
