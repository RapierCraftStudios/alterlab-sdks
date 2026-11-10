"""Coverage for #31823: the server's sync-poll-timeout downgrade
(``202 {job_id, sync_downgraded: true}``, replacing the old ``504``) must not
be mistaken for a completed scrape, and ``wait_for_job`` must resolve a job
whose terminal status is the canonical ``"succeeded"`` value (not the legacy
``"completed"`` the SDK previously hardcoded).
"""

import json

import httpx
import pytest

from alterlab import AlterLab
from alterlab.client import JobFailedError


def _mount_mock_transport(client: AlterLab, handler) -> None:
    """Swap the client's internal httpx.AsyncClient for one backed by a
    MockTransport, so tests never make real network calls."""
    client.client = httpx.AsyncClient(
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_scrape_polls_through_sync_downgrade_and_returns_real_result():
    """A sync_downgraded 202 must not be returned to the caller as-is —
    scrape() should poll until the job succeeds and return the real result."""
    job_id = "job-downgrade-1"
    calls = {"jobs_polled": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/scrape":
            return httpx.Response(
                202,
                json={
                    "job_id": job_id,
                    "sync_downgraded": True,
                    "reason": "Request exceeded the 85s synchronous window",
                    "poll_url": f"/api/v1/jobs/{job_id}",
                },
            )
        if request.method == "GET" and request.url.path == f"/api/v1/jobs/{job_id}":
            calls["jobs_polled"] += 1
            if calls["jobs_polled"] == 1:
                return httpx.Response(200, json={"job_id": job_id, "status": "queued"})
            return httpx.Response(
                200,
                json={
                    "job_id": job_id,
                    "status": "succeeded",
                    "result": {
                        "url": "https://example.com",
                        "content": "real scraped content",
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.scrape(
            "https://example.com", poll_interval=0.01, poll_timeout=5
        )
    finally:
        await client.close()

    assert result == {"url": "https://example.com", "content": "real scraped content"}
    assert "sync_downgraded" not in result
    assert calls["jobs_polled"] == 2


@pytest.mark.asyncio
async def test_scrape_returns_async_envelope_when_sync_false():
    """An explicit sync=False request must not poll — it gets the job
    envelope back immediately, same as before this fix."""
    job_id = "job-async-1"
    polled = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/scrape":
            return httpx.Response(202, json={"job_id": job_id})
        polled["count"] += 1
        raise AssertionError("should not poll for an explicit async request")

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.scrape("https://example.com", sync=False)
    finally:
        await client.close()

    assert result["job_id"] == job_id
    assert polled["count"] == 0


@pytest.mark.asyncio
async def test_scrape_serializes_wait_until_deadline_policy():
    """The Python SDK sends the same policy name accepted by the REST API."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.read()))
        return httpx.Response(200, json={"status_code": 200, "content": {}})

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.scrape(
            "https://example.com",
            sync_policy="wait_until_deadline",
        )
    finally:
        await client.close()

    assert result["status_code"] == 200
    assert seen["sync"] is True
    assert seen["sync_policy"] == "wait_until_deadline"


@pytest.mark.asyncio
async def test_scrape_rejects_wait_policy_with_async_mode():
    client = AlterLab(api_key="sk_test_dummy")
    try:
        with pytest.raises(Exception, match="requires sync=True"):
            await client.scrape(
                "https://example.com",
                sync=False,
                sync_policy="wait_until_deadline",
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_wait_for_job_resolves_on_succeeded_status():
    """wait_for_job must treat the canonical 'succeeded' status as terminal
    success, not raise 'Unknown job status'."""
    job_id = "job-succeeded-1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job_id": job_id,
                "status": "succeeded",
                "result": {"url": "https://example.com", "content": "ok"},
            },
        )

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.wait_for_job(job_id, poll_interval=0.01, poll_timeout=5)
    finally:
        await client.close()

    assert result == {"url": "https://example.com", "content": "ok"}


@pytest.mark.asyncio
async def test_wait_for_job_continues_through_queued_and_retrying():
    """'queued' and 'retrying' are valid in-progress JobStatus values and
    must not raise 'Unknown job status'."""
    job_id = "job-queued-1"
    statuses = iter(["queued", "retrying", "succeeded"])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        body = {"job_id": job_id, "status": status}
        if status == "succeeded":
            body["result"] = {}
        return httpx.Response(200, json=body)

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.wait_for_job(job_id, poll_interval=0.01, poll_timeout=5)
    finally:
        await client.close()

    assert result == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "rejected", "cancelled"])
async def test_wait_for_job_raises_job_failed_error_on_terminal_failure(status):
    job_id = f"job-{status}-1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"job_id": job_id, "status": status, "error": "boom"}
        )

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        with pytest.raises(JobFailedError):
            await client.wait_for_job(job_id, poll_interval=0.01, poll_timeout=5)
    finally:
        await client.close()


# #31889: the fix that added the canonical/new statuses above (`queued`,
# `retrying`, `succeeded`, `rejected`, `cancelled`) explicitly preserves the
# legacy `completed` success alias (`_JOB_STATUS_SUCCEEDED = frozenset({
# "succeeded", "completed"})`) and the original `pending`/`running`
# in-progress statuses — neither branch had a test until now.
@pytest.mark.asyncio
async def test_wait_for_job_resolves_on_legacy_completed_status():
    """wait_for_job must still treat the legacy 'completed' status as
    terminal success, for backward compatibility with historical rows."""
    job_id = "job-completed-1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job_id": job_id,
                "status": "completed",
                "result": {"url": "https://example.com", "content": "legacy ok"},
            },
        )

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.wait_for_job(job_id, poll_interval=0.01, poll_timeout=5)
    finally:
        await client.close()

    assert result == {"url": "https://example.com", "content": "legacy ok"}


@pytest.mark.asyncio
async def test_wait_for_job_continues_through_legacy_pending_and_running():
    """'pending' and 'running' are the original in-progress JobStatus values
    and must not raise 'Unknown job status'."""
    job_id = "job-pending-1"
    statuses = iter(["pending", "running", "succeeded"])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        body = {"job_id": job_id, "status": status}
        if status == "succeeded":
            body["result"] = {}
        return httpx.Response(200, json=body)

    client = AlterLab(api_key="sk_test_dummy")
    _mount_mock_transport(client, handler)
    try:
        result = await client.wait_for_job(job_id, poll_interval=0.01, poll_timeout=5)
    finally:
        await client.close()

    assert result == {}
