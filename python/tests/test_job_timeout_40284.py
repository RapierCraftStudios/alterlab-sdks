"""#40284: a poll timeout raises a typed JobTimeoutError (job_id, poll_url)
that is still an AlterLabTimeoutError, so existing handlers keep working."""

import httpx
import pytest

from alterlab import AlterLab, AlterLabTimeoutError
from alterlab.client import JobTimeoutError


def _mount(client: AlterLab, handler) -> None:
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_wait_for_job_timeout_raises_job_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-slow", "status": "running"})

    client = AlterLab(api_key="sk_test_dummy")
    _mount(client, handler)
    with pytest.raises(JobTimeoutError) as excinfo:
        await client.wait_for_job("job-slow", poll_interval=0.001, poll_timeout=0.01)
    err = excinfo.value
    assert isinstance(err, AlterLabTimeoutError)
    assert err.job_id == "job-slow"
    assert err.poll_url == "/api/v1/jobs/job-slow"
    assert "did not complete within" in str(err)
