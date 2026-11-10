"""Coverage for #34582: 429 handling honours Retry-After with jitter, stops at
``max_retry_wait`` instead of blocking for minutes, and surfaces the canonical
429 body fields (#34574) on :class:`RateLimitError`.
"""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

import alterlab.client as client_module
from alterlab import AlterLab, AlterLabAPIError, RateLimitError
from alterlab.client import _compute_retry_sleep, _parse_retry_after

CANONICAL_429 = {
    "error": "rate_limit_exceeded",
    "message": "Rate limit for your plan (Free): 30 requests/minute. Retry in 2s.",
    "detail": {
        "scope": "account",
        "limit": 30,
        "account_tier": "free",
        "retry_after_seconds": 2,
    },
    "docs_url": "https://alterlab.io/docs/reference/limits",
}

CANONICAL_HEADERS = {
    "Retry-After": "2",
    "RateLimit-Limit": "30",
    "RateLimit-Remaining": "0",
    "RateLimit-Reset": "2",
    "X-RateLimit-Scope": "account",
}


def _make_client(handler, **kwargs) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy", **kwargs)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.fixture
def sleeps(monkeypatch):
    """Record requested sleeps instead of sleeping."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    return recorded


@pytest.mark.asyncio
async def test_canonical_429_surfaces_fields_and_waits_at_least_retry_after(sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=CANONICAL_429, headers=CANONICAL_HEADERS)

    client = _make_client(handler, max_retries=3, retry_delay=0.01)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert err.status_code == 429
    assert err.retry_after == 2.0
    assert err.error_code == "rate_limit_exceeded"
    assert err.message == CANONICAL_429["message"]
    assert err.scope == "account"
    assert err.limit == 30
    assert err.account_tier == "free"
    assert err.docs_url == "https://alterlab.io/docs/reference/limits"
    assert err.rate_limit_limit == "30"
    assert err.rate_limit_remaining == "0"
    assert err.rate_limit_reset == "2"

    # 3 attempts -> 2 sleeps, none after the final attempt; each honours the
    # Retry-After floor plus at most 20% jitter.
    assert len(sleeps) == 2
    for s in sleeps:
        assert 2.0 <= s <= 2.4


@pytest.mark.asyncio
async def test_canonical_429_detail_stays_a_string(sleeps):
    """#34607: the canonical body's ``detail`` is an object, but
    ``AlterLabAPIError.detail`` is typed ``str`` — it must carry the
    human-readable ``message``, not the raw dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=CANONICAL_429, headers=CANONICAL_HEADERS)

    client = _make_client(handler, max_retries=1)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert err.detail == CANONICAL_429["message"]
    assert str(err) == f"API Error 429: {CANONICAL_429['message']}"
    # Structured fields are still parsed from the response body.
    assert err.scope == "account"
    assert err.limit == 30
    assert err.retry_after == 2.0


@pytest.mark.asyncio
async def test_canonical_envelope_detail_on_non_429_stays_a_string(sleeps):
    body = {
        "error": "spend_limit_exceeded",
        "message": "Monthly spend limit reached.",
        "detail": {"scope": "spend", "limit": 100},
        "docs_url": "https://alterlab.io/docs/reference/limits",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json=body)

    client = _make_client(handler, max_retries=1)
    with pytest.raises(AlterLabAPIError) as exc_info:
        await client.get_usage()
    assert exc_info.value.detail == "Monthly spend limit reached."


@pytest.mark.asyncio
async def test_plain_string_detail_is_unchanged(sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Invalid URL"})

    client = _make_client(handler, max_retries=1)
    with pytest.raises(AlterLabAPIError) as exc_info:
        await client.get_usage()
    assert exc_info.value.detail == "Invalid URL"


@pytest.mark.asyncio
async def test_edge_429_without_json_raises_rate_limit_error(sleeps):
    """A Cloudflare 1015 is plain text and may carry no Retry-After."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="error code: 1015")

    client = _make_client(handler, max_retries=2, retry_delay=1.0)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert err.detail == "error code: 1015"
    assert err.retry_after is None
    assert err.error_code is None
    assert err.scope is None
    assert err.limit is None
    # Jittered exponential backoff without a server hint: base 1s -> [0.5, 1].
    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 1.0


@pytest.mark.asyncio
async def test_edge_429_with_http_date_retry_after_does_not_crash(sleeps):
    retry_at = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, text="error code: 1015", headers={"Retry-After": retry_at}
        )

    client = _make_client(handler, max_retries=1)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()
    assert 25 <= exc_info.value.retry_after <= 30
    assert sleeps == []


@pytest.mark.asyncio
async def test_retry_after_beyond_max_wait_raises_immediately(sleeps):
    """A 600s Retry-After must not block the call; the error carries it."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            429, json=CANONICAL_429, headers={**CANONICAL_HEADERS, "Retry-After": "600"}
        )

    client = _make_client(handler, max_retries=5, max_retry_wait=30)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    assert calls["n"] == 1
    assert sleeps == []
    assert exc_info.value.retry_after == 600.0


@pytest.mark.asyncio
async def test_max_retry_wait_caps_total_sleep_across_attempts(sleeps):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json=CANONICAL_429, headers=CANONICAL_HEADERS)

    # Each wait is 2-2.4s; a 5s budget fits two of them, never three.
    client = _make_client(handler, max_retries=10, retry_delay=0.01, max_retry_wait=5)
    with pytest.raises(RateLimitError):
        await client.get_usage()

    assert len(sleeps) == 2
    assert sum(sleeps) <= 5
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_429_then_success_returns_response(sleeps):
    responses = iter(
        [
            httpx.Response(429, json=CANONICAL_429, headers=CANONICAL_HEADERS),
            httpx.Response(200, json={"credits": 1}),
        ]
    )

    client = _make_client(lambda request: next(responses), retry_delay=0.01)
    assert await client.get_usage() == {"credits": 1}
    assert len(sleeps) == 1


def test_max_retry_wait_rejects_negative():
    with pytest.raises(ValueError):
        AlterLab(api_key="sk_test_dummy", max_retry_wait=-1)


def test_parse_retry_after_forms():
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("garbage") is None
    assert _parse_retry_after("nan") is None
    assert _parse_retry_after("7") == 7.0
    assert _parse_retry_after("-3") == 0.0
    past = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1), usegmt=True)
    assert _parse_retry_after(past) == 0.0


def test_backoff_is_jittered():
    samples = {_compute_retry_sleep(3, 1.0, None) for _ in range(50)}
    assert len(samples) > 1
    assert all(4.0 <= s <= 8.0 for s in samples)
    with_hint = {_compute_retry_sleep(0, 1.0, 10.0) for _ in range(50)}
    assert len(with_hint) > 1
    assert all(10.0 <= s <= 12.0 for s in with_hint)
