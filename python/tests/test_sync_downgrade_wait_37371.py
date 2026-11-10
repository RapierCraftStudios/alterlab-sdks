"""#37371: after a sync_downgraded 202 the SDK long-polls ``?wait=N`` and
returns the result as soon as the first long-poll reports it."""

import httpx
import pytest

from alterlab import AlterLab


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_downgrade_uses_server_long_poll_and_returns_result():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "j1", "sync_downgraded": True, "poll_url": "/api/v1/jobs/j1"}
            )
        seen.append(request.url.params.get("wait"))
        return httpx.Response(
            200,
            json={"status": "succeeded", "result": {"url": "https://e.com", "status_code": 200}},
        )

    out = await _client(handler).scrape("https://e.com")
    assert seen == ["20"]
    assert out is not None


@pytest.mark.asyncio
async def test_plain_wait_for_job_has_no_wait_param():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("wait"))
        return httpx.Response(200, json={"status": "succeeded", "result": {}})

    await _client(handler).wait_for_job("j1")
    assert seen == [None]
