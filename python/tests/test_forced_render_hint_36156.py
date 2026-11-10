"""#36156: the SDK exposes the API's forced-render retry hint (``error.hint``).

The hint is additive: ``detail`` stays a str (#34607) and errors without a hint
report ``hint is None``.
"""

import httpx
import pytest

from alterlab import (
    AdvancedOptions,
    AlterLab,
    AlterLabAPIError,
    ForcedRenderHint,
    JobFailedError,
    get_error_hint,
)

HINT = {
    "code": "render_js_auto",
    "reason": "challenge",
    "message": (
        "This request forced browser rendering and the page returned a verification "
        'screen instead of content. Retrying with render_js="auto" lets the platform '
        "start at the lowest tier that returns the page."
    ),
}


def _mount(client: AlterLab, handler) -> None:
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )


def _sync_422(error: dict) -> httpx.Response:
    return httpx.Response(
        422,
        json={"detail": f"{error['error_code']}: {error['message']}", "error": error},
    )


@pytest.mark.asyncio
async def test_sync_422_with_hint_populates_api_error_hint():
    error = {"error_code": "anti_bot_blocked", "message": "Blocked", "hint": HINT}

    def handler(request: httpx.Request) -> httpx.Response:
        return _sync_422(error)

    client = AlterLab(api_key="sk_test_x", max_retries=1)
    _mount(client, handler)
    try:
        with pytest.raises(AlterLabAPIError) as exc_info:
            await client.scrape(
                "https://example.com", advanced=AdvancedOptions(render_js=True)
            )
    finally:
        await client.close()

    err = exc_info.value
    assert err.status_code == 422
    assert isinstance(err.detail, str)
    assert err.detail == "anti_bot_blocked: Blocked"
    assert err.hint == HINT
    assert get_error_hint(err) == HINT
    assert str(err) == "API Error 422: anti_bot_blocked: Blocked"


@pytest.mark.asyncio
async def test_sync_422_without_hint_has_no_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return _sync_422({"error_code": "anti_bot_blocked", "message": "Blocked"})

    client = AlterLab(api_key="sk_test_x", max_retries=1)
    _mount(client, handler)
    try:
        with pytest.raises(AlterLabAPIError) as exc_info:
            await client.scrape("https://example.com")
    finally:
        await client.close()

    assert exc_info.value.hint is None
    assert get_error_hint(exc_info.value) is None


@pytest.mark.asyncio
async def test_wait_for_job_failure_exposes_hint():
    job_id = "job-hint-1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job_id": job_id,
                "status": "failed",
                "error": {
                    "code": "TIMEOUT",
                    "message": "Job exceeded timeout",
                    "hint": HINT,
                },
            },
        )

    client = AlterLab(api_key="sk_test_x", max_retries=1)
    _mount(client, handler)
    try:
        with pytest.raises(JobFailedError) as exc_info:
            await client.wait_for_job(job_id, poll_interval=0.01)
    finally:
        await client.close()

    err = exc_info.value
    assert isinstance(err, AlterLabAPIError)
    assert err.hint == HINT
    assert get_error_hint(err) == HINT
    assert str(err).startswith(f"Job {job_id} ended with status 'failed': ")


def test_job_failed_error_with_string_detail_has_no_hint():
    err = JobFailedError("job-1", "failed", "plain failure")
    assert err.hint is None
    assert str(err) == "Job job-1 ended with status 'failed': plain failure"


def test_get_error_hint_from_crawl_page_error_dict():
    page = {"url": "https://example.com/a", "status": "failed", "error": {"hint": HINT}}
    hint = get_error_hint(page["error"])
    assert hint == HINT
    assert hint["code"] == "render_js_auto"


@pytest.mark.parametrize(
    "error",
    [
        None,
        "string error",
        {},
        {"hint": "not-a-dict"},
        {"hint": {"code": "render_js_auto"}},
        {"hint": {"message": "missing code"}},
        {"hint": {"code": 1, "message": "bad code type"}},
    ],
)
def test_get_error_hint_rejects_absent_or_malformed(error):
    assert get_error_hint(error) is None


def test_hint_keeps_only_known_keys():
    hint = get_error_hint({"hint": {**HINT, "internal": "x"}})
    assert hint == HINT
    assert set(ForcedRenderHint.__annotations__) == {"code", "reason", "message"}
