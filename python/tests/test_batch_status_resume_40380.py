"""Coverage for #40380: get_batch_status / resume_batch expose the batch
``paused_low_success`` stop (GET /batch/{id}, POST /batch/{id}/resume)."""

import httpx
import pytest

from alterlab import AlterLab, AlterLabSync

STATUS = {
    "batch_id": "b1",
    "status": "paused_low_success",
    "paused": 3,
    "paused_reason": {"code": "low_success", "domain": "example.com"},
}
RESUME = {"batch_id": "b1", "resumed": 3, "status": "processing"}


def _client(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=RESUME if request.method == "POST" else STATUS)

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_get_batch_status_passes_paused_fields():
    captured = []
    result = await _client(captured).get_batch_status("b1")
    assert result == STATUS
    assert (captured[0].method, captured[0].url.path) == ("GET", "/api/v1/batch/b1")


@pytest.mark.asyncio
async def test_resume_batch_posts_to_resume():
    captured = []
    result = await _client(captured).resume_batch("b1")
    assert result == RESUME
    assert (captured[0].method, captured[0].url.path) == (
        "POST",
        "/api/v1/batch/b1/resume",
    )


def test_sync_wrappers_exist():
    assert callable(AlterLabSync.get_batch_status)
    assert callable(AlterLabSync.resume_batch)
