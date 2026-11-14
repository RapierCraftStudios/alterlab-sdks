"""Coverage for #40828: get_batch_status sends include/limit/offset."""

import httpx
import pytest

from alterlab import AlterLab

STATUS = {"batch_id": "b1", "status": "processing", "total": 2, "items": []}


def _client(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=STATUS)

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_get_batch_status_sends_include_and_paging():
    captured = []
    result = await _client(captured).get_batch_status(
        "b1", include="counts", limit=10, offset=20
    )
    assert result == STATUS
    assert captured[0].url.path == "/api/v1/batch/b1"
    assert dict(captured[0].url.params) == {
        "include": "counts",
        "limit": "10",
        "offset": "20",
    }


@pytest.mark.asyncio
async def test_get_batch_status_without_options_sends_no_params():
    captured = []
    await _client(captured).get_batch_status("b1")
    assert dict(captured[0].url.params) == {}
