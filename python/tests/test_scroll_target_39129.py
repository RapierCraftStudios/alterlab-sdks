"""#39129: scroll action carries target_selector (API ScrollAction mirror)."""

import json

import httpx
import pytest

from alterlab import Actions, AdvancedOptions, AlterLab, ScrollAction


def test_target_selector_serialises():
    assert Actions.scroll(target_selector=".row-42").to_dict() == {
        "type": "scroll",
        "direction": "down",
        "amount": 1,
        "target_selector": ".row-42",
    }


def test_unset_target_selector_is_omitted():
    assert Actions.scroll().to_dict() == {
        "type": "scroll",
        "direction": "down",
        "amount": 1,
    }


@pytest.mark.parametrize("value", ["", "   ", "x" * 501])
def test_invalid_target_selector_rejected(value):
    with pytest.raises(ValueError):
        ScrollAction(target_selector=value)


def test_max_length_selector_accepted():
    assert ScrollAction(target_selector="x" * 500).to_dict()["target_selector"]


@pytest.mark.asyncio
async def test_scrape_request_carries_target_selector():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"url": "https://example.com"})

    client = AlterLab(api_key="sk_test_x", max_retries=1)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    try:
        await client.scrape(
            "https://example.com",
            advanced=AdvancedOptions(render_js=True),
            actions=[Actions.scroll(target_selector="#row-9")],
        )
    finally:
        await client.close()

    assert bodies[0]["advanced"]["actions"] == [
        {
            "type": "scroll",
            "direction": "down",
            "amount": 1,
            "target_selector": "#row-9",
        }
    ]
