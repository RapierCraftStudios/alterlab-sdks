"""#36243: the SDK exposes the API's opt-in ``cost_controls.fallback_on_block``."""

import json

import httpx
import pytest

from alterlab import AlterLab, AlterLabAPIError, CostControls


def test_fallback_on_block_omitted_by_default():
    assert "fallback_on_block" not in CostControls().to_dict()
    assert "fallback_on_block" not in CostControls(fallback_on_block=False).to_dict()


def test_fallback_on_block_true_is_serialized():
    cc = CostControls(force_tier="4", fallback_on_block=True)
    assert cc.fallback_on_block is True
    assert cc.to_dict()["fallback_on_block"] is True
    assert cc.to_dict()["force_tier"] == "4"


@pytest.mark.asyncio
async def test_scrape_sends_fallback_on_block():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(422, json={"detail": "anti_bot_blocked: Blocked"})

    client = AlterLab(api_key="sk_test_x", max_retries=1)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(AlterLabAPIError):
            await client.scrape(
                "https://example.com",
                cost_controls=CostControls(force_tier="4", fallback_on_block=True),
            )
    finally:
        await client.close()

    assert bodies[0]["cost_controls"]["fallback_on_block"] is True
    assert bodies[0]["cost_controls"]["force_tier"] == "4"
