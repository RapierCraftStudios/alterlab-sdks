"""#40335 (ALT-311/313): every SDK error is typed with code/retryable/request_id
and structured ``detail`` never renders as a raw dict repr."""

import httpx
import pytest

from alterlab import (
    ERROR_CLASSES,
    ERROR_CODES,
    AlterLab,
    AlterLabAPIError,
    AlterLabError,
    InsufficientFundsError,
    ConnectionFailedError,
    RateLimitError,
)
from alterlab import _transport as t


def _client(handler, **kwargs) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy", max_retries=1, **kwargs)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


async def _raised(handler) -> Exception:
    client = _client(handler)
    with pytest.raises(Exception) as info:
        await client._request_with_retry("POST", "/api/v1/scrape", json={})
    return info.value


@pytest.mark.asyncio
async def test_structured_detail_is_text_and_typed():
    def handler(request):
        return httpx.Response(
            400,
            json={"detail": {"code": "bad_request", "message": "urls[0] too long"}},
            headers={"X-Request-ID": "req-1"},
        )

    err = await _raised(handler)
    assert isinstance(err, AlterLabAPIError)
    assert isinstance(err, t.BadRequestError)
    assert err.code == "bad_request"
    assert err.retryable is False
    assert err.request_id == "req-1"
    assert "urls[0] too long" in str(err)


@pytest.mark.asyncio
async def test_5xx_retryable_with_body_request_id():
    err = await _raised(
        lambda r: httpx.Response(503, json={"request_id": "req-9", "detail": "down"})
    )
    assert isinstance(err, AlterLabAPIError)
    assert err.retryable is True
    assert err.request_id == "req-9"
    assert err.code


@pytest.mark.asyncio
async def test_402_keeps_legacy_class_with_typed_fields():
    err = await _raised(
        lambda r: httpx.Response(
            402, json={"detail": {"error": "insufficient_credits", "message": "Empty"}}
        )
    )
    assert isinstance(err, InsufficientFundsError)
    assert err.code == "insufficient_credits"
    assert err.retryable is False


@pytest.mark.asyncio
async def test_429_typed_retry_after():
    err = await _raised(
        lambda r: httpx.Response(
            429,
            json={"error": "rate_limit_exceeded", "detail": {"retry_after_seconds": 2}},
            headers={"Retry-After": "2", "X-Request-ID": "req-r"},
        )
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after_seconds == 2
    assert err.retryable is True
    assert err.request_id == "req-r"


@pytest.mark.asyncio
async def test_network_failure_is_typed():
    def handler(request):
        raise httpx.ConnectError("boom")

    client = _client(handler)
    with pytest.raises(ConnectionFailedError) as info:
        await client._request_with_retry("GET", "/api/v1/jobs/x")
    assert info.value.code == "network_error"
    assert info.value.retryable is True
    assert not isinstance(info.value, httpx.HTTPError)


def test_every_documented_code_has_a_class():
    for code in ERROR_CODES:
        if code in ("network_error", "request_cancelled"):
            continue
        cls = ERROR_CLASSES[code]
        assert issubclass(cls, AlterLabAPIError)
        assert cls.code == code or code in (
            "rate_limited",
            "rate_limit_exceeded",
            "unauthorized",
            "insufficient_credits",
        )
    assert issubclass(ConnectionFailedError, AlterLabError)


def test_describe_detail():
    assert t.describe_detail([{"msg": "a"}, "b"]) == "a; b"
    assert t.describe_detail({"x": 1}) == '{"x": 1}'
