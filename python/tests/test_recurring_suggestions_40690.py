"""#40690: ``suggestions`` opt-out is sent only when set; the result field passes through."""

import json

import httpx
import pytest

from alterlab import AlterLab

SUGGESTION = {
    "type": "schedule",
    "reason": "6 similar pages",
    "tool": "alterlab_schedule",
    "endpoint": "POST /api/v1/schedules",
    "create": {"name": "Re-scrape e.com", "urls": ["https://e.com/1"], "cron": "0 9 * * *"},
    "estimated_run_cost_microcents": 1000,
    "estimated_monthly_cost_microcents": 30000,
    "docs_url": "https://alterlab.io/docs",
}


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test_dummy")
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_suggestions_passthrough_and_default_omitted():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"content": "hi", "status_code": 200, "suggestions": [SUGGESTION]}
        )

    result = await _client(handler).scrape("https://e.com/1")
    assert "suggestions" not in seen
    assert result["suggestions"][0]["create"]["cron"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_suggestions_false_is_forwarded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"content": "hi", "status_code": 200})

    await _client(handler).scrape("https://e.com/1", suggestions=False)
    assert seen["suggestions"] is False
