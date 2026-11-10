"""#36652: ``scrape(actions_on_error=...)`` reaches ``advanced.actions_on_error``.

Per-action ``optional``/``timeout_ms`` ride inside the action dicts unchanged;
``actions_on_error`` is validated client-side and omitted when unset.
"""

import json

import httpx
import pytest

from alterlab import AdvancedOptions, AlterLab, AlterLabValidationError

_OK = {
    "url": "https://example.com",
    "status_code": 200,
    "content": {"markdown": "ok"},
    "action_results": [
        {"index": 0, "type": "click", "success": True, "duration_ms": 12}
    ],
    "actions_status": "complete",
}


def _capture(client: AlterLab, bodies: list) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_OK)

    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )


ACTIONS = [{"type": "click", "selector": "#a", "optional": False, "timeout_ms": 500}]


@pytest.mark.asyncio
async def test_actions_on_error_is_sent_in_advanced():
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    bodies: list = []
    _capture(client, bodies)

    result = await client.scrape(
        "https://example.com",
        advanced=AdvancedOptions(render_js=True),
        actions=ACTIONS,
        actions_on_error="abort",
    )

    assert bodies[0]["advanced"]["actions_on_error"] == "abort"
    assert bodies[0]["advanced"]["actions"] == ACTIONS
    assert result is not None


@pytest.mark.asyncio
async def test_actions_on_error_omitted_by_default():
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    bodies: list = []
    _capture(client, bodies)

    await client.scrape(
        "https://example.com",
        advanced=AdvancedOptions(render_js=True),
        actions=[{"type": "click", "selector": "#a"}],
    )

    assert "actions_on_error" not in bodies[0]["advanced"]


@pytest.mark.asyncio
async def test_invalid_actions_on_error_is_rejected():
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    with pytest.raises(AlterLabValidationError, match="actions_on_error"):
        await client.scrape(
            "https://example.com",
            advanced=AdvancedOptions(render_js=True),
            actions=ACTIONS,
            actions_on_error="stop",
        )
