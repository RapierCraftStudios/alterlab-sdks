"""#41159: JobFailedError carries the #40689 failure envelope."""

import httpx
import pytest

from alterlab import AlterLab
from alterlab.client import JobFailedError


async def _fail(payload: dict) -> JobFailedError:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "j", "status": "failed", **payload})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(JobFailedError) as info:
            await client.wait_for_job("j", poll_interval=0.01, poll_timeout=5)
        return info.value
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_envelope_fields_exposed_unchanged():
    action = {"type": "wait", "params": {"retry_after": 30}}
    err = await _fail(
        {
            "error": {
                "message": "origin down",
                "error_code": "origin_unreachable",
                "retryable": False,
                "charged": False,
                "auto_retry": "none",
                "retry_after_s": 30,
                "next_action": action,
            }
        }
    )
    assert err.code == "origin_unreachable"
    assert err.error_code == "origin_unreachable"
    assert err.retryable is False
    assert err.charged is False
    assert err.auto_retry == "none"
    assert err.retry_after_s == 30
    assert err.next_action == action


@pytest.mark.asyncio
async def test_job_level_next_action_and_retryable():
    err = await _fail(
        {
            "error": {
                "message": "x",
                "error_code": "origin_unavailable",
                "retryable": True,
            },
            "next_action": {"type": "retry"},
        }
    )
    assert err.retryable is True
    assert err.next_action == {"type": "retry"}


@pytest.mark.asyncio
async def test_string_error_keeps_defaults():
    err = await _fail({"error": "boom"})
    assert err.code == "job_failed"
    assert err.error_code is None
    assert err.retryable is False
    assert err.retry_after_s is None
    assert err.charged is None
    assert err.auto_retry is None
    assert err.next_action is None
