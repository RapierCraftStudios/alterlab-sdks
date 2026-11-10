"""#37906: get_job_status exposes the server long-poll ``wait`` query param."""

import httpx
import pytest

from alterlab import AlterLab
from alterlab.client import AlterLabSync, JobExpiredError


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


def _ok(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("wait"))
        return httpx.Response(200, json={"status": "succeeded"})

    return handler


@pytest.mark.asyncio
async def test_default_sends_no_wait_param():
    seen = []
    out = await _client(_ok(seen)).get_job_status("j1")
    assert seen == [None]
    assert out["status"] == "succeeded"


@pytest.mark.asyncio
async def test_wait_sends_query_param():
    seen = []
    await _client(_ok(seen)).get_job_status("j1", wait=10)
    assert seen == ["10"]


@pytest.mark.asyncio
async def test_negative_wait_rejected():
    with pytest.raises(ValueError):
        await _client(_ok([])).get_job_status("j1", wait=-1)


@pytest.mark.asyncio
async def test_404_still_job_expired_with_wait():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    with pytest.raises(JobExpiredError):
        await _client(handler).get_job_status("j1", wait=5)


def test_sync_wrapper_forwards_wait():
    calls = []

    class _Stub:
        async def get_job_status(self, job_id, wait=0):
            calls.append((job_id, wait))
            return {"status": "succeeded"}

    sync = AlterLabSync.__new__(AlterLabSync)
    sync._client = _Stub()
    sync._run = lambda coro: __import__("asyncio").run(coro)
    assert sync.get_job_status("j1", wait=7) == {"status": "succeeded"}
    assert calls == [("j1", 7)]
