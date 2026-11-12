"""Coverage for #40438: tag approval methods forward ``X-Organization-Id``."""

import httpx
import pytest

from alterlab import AlterLab


def _make_client(captured) -> AlterLab:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("x-organization-id"))
        return httpx.Response(200, json={"approval_above_usd": 1.0})

    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_tag_approval_sends_org_header_when_set():
    captured = []
    client = _make_client(captured)
    await client.get_tag_approval("nightly", organization_id="org_1")
    await client.set_tag_approval("nightly", 5.0, organization_id="org_2")
    assert captured == ["org_1", "org_2"]


@pytest.mark.asyncio
async def test_tag_approval_omits_org_header_by_default():
    captured = []
    client = _make_client(captured)
    await client.get_tag_approval("nightly")
    await client.set_tag_approval("nightly", None)
    assert captured == [None, None]
