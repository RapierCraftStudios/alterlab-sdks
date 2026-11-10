"""Coverage for #36240: the repeat-failure back-off 429 (#36158) surfaces its
``detail`` fields and hint on :class:`RateLimitError`."""

import httpx
import pytest

import alterlab.client as client_module
from alterlab import AlterLab, RateLimitError
from alterlab._failure_backoff import parse_failure_backoff_detail

BACKOFF_HINT = {
    "code": "repeat_failure_backoff",
    "message": (
        "This exact request returned a verification challenge 3 times in a row, "
        "so it was paused for 60s and no credits were charged."
    ),
}

BACKOFF_429 = {
    "error": "repeat_failure_backoff",
    "message": BACKOFF_HINT["message"],
    "detail": {
        "scope": "url",
        "limit": 3,
        "account_tier": "free",
        "retry_after_seconds": 60,
        "consecutive_failures": 3,
        "outcome_class": "challenge",
        "failure_code": "CAPTCHA_REQUIRED",
        "hint": BACKOFF_HINT,
    },
    "docs_url": "https://alterlab.io/docs/reference/error-codes",
}

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
async def test_backoff_429_surfaces_fields_and_hint(sleeps, monkeypatch):
    # Maximum jitter so the Retry-After wait deterministically exceeds the
    # default max_retry_wait (60s).
    monkeypatch.setattr(client_module.random, "uniform", lambda a, b: b)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429,
            json=BACKOFF_429,
            headers={"Retry-After": "60", "X-AlterLab-Credits": "0"},
        )

    client = _make_client(handler)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert len(calls) == 1
    assert sleeps == []
    assert err.retry_after == 60.0
    assert err.error_code == "repeat_failure_backoff"
    assert err.scope == "url"
    assert err.consecutive_failures == 3
    assert err.outcome_class == "challenge"
    assert err.failure_code == "CAPTCHA_REQUIRED"
    assert err.hint is not None
    assert err.hint["code"] == "repeat_failure_backoff"
    assert err.hint["message"] == BACKOFF_HINT["message"]
    assert err.hint["reason"] == ""


@pytest.mark.asyncio
async def test_canonical_429_leaves_backoff_fields_unset(sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=CANONICAL_429, headers={"Retry-After": "2"})

    client = _make_client(handler, max_retries=1)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert err.error_code == "rate_limit_exceeded"
    assert err.consecutive_failures is None
    assert err.outcome_class is None
    assert err.failure_code is None
    assert err.hint is None


@pytest.mark.asyncio
@pytest.mark.parametrize("count", ["3", True, 2.5])
async def test_malformed_backoff_values_are_ignored(sleeps, count):
    body = {
        **BACKOFF_429,
        "detail": {
            **BACKOFF_429["detail"],
            "consecutive_failures": count,
            "outcome_class": 1,
            "failure_code": None,
            "hint": {"code": "repeat_failure_backoff"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=body)

    client = _make_client(handler, max_retries=1)
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_usage()

    err = exc_info.value
    assert err.consecutive_failures is None
    assert err.outcome_class is None
    assert err.failure_code is None
    assert err.hint is None


@pytest.mark.parametrize("detail", [None, {}, "not a dict", []])
def test_parse_failure_backoff_detail_empty(detail):
    assert parse_failure_backoff_detail(detail) == (None, None, None)


def test_parse_failure_backoff_detail_values():
    assert parse_failure_backoff_detail(BACKOFF_429["detail"]) == (
        3,
        "challenge",
        "CAPTCHA_REQUIRED",
    )
