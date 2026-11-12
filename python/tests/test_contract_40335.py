"""#40335 contract tests: batch body (ALT-310), wait_for_job statuses
(ALT-312), spend-limit error, and the generated operation table (SDK <-> MCP
parity extension from #40286)."""

import json

import httpx
import pytest

from alterlab import AlterLab, AlterLabAPIError, JobFailedError
from alterlab import _transport as t


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy", max_retries=1)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_batch_body_and_rejected_items():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "batch_id": "b1",
                "total": 2,
                "accepted": 1,
                "rejected_items": [{"index": 1, "url": "x", "error": "too long"}],
                "items": [],
            },
        )

    result = await _client(handler).batch_scrape([{"url": "https://a.example"}])
    assert seen["body"]["urls"][0]["url"] == "https://a.example"
    assert len(result["rejected_items"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "rejected", "cancelled"])
async def test_wait_for_job_terminal_failures(status):
    def handler(request):
        return httpx.Response(
            200, json={"job_id": "j1", "status": status, "error": "nope"}
        )

    with pytest.raises(JobFailedError) as info:
        await _client(handler).wait_for_job("j1", poll_interval=0.01)
    assert info.value.status == status
    assert info.value.code == "job_failed"


@pytest.mark.asyncio
async def test_spend_limit_error_is_typed():
    def handler(request):
        return httpx.Response(
            402,
            json={
                "detail": {
                    "error": "spend_limit_exceeded",
                    "message": "Spend limit reached",
                }
            },
            headers={"X-Request-ID": "req-s"},
        )

    with pytest.raises(AlterLabAPIError) as info:
        await _client(handler)._request_with_retry("POST", "/api/v1/scrape", json={})
    assert info.value.request_id == "req-s"
    assert info.value.retryable is False
    assert "Spend limit reached" in str(info.value)


def test_generated_operations_cover_parity_routes():
    ops = {(o["method"], o["path"]) for o in t.OPERATIONS}
    for route in [
        ("POST", "/api/v1/scrape"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("POST", "/api/v1/batch"),
        ("POST", "/api/v1/agent/support-ticket"),
        ("POST", "/api/v1/feedback/scrape"),
    ]:
        assert route in ops
