"""#36661: typed browser actions serialise to API JSON; action_results are typed."""

import json

import httpx
import pytest

from alterlab import (
    ActionResult,
    Actions,
    AdvancedOptions,
    AlterLab,
    AlterLabValidationError,
    ClickAction,
    DismissConsentAction,
    EvaluateAction,
    WaitAction,
)

ACTION_RESULTS = [
    {"index": 0, "type": "click", "success": True, "error": None, "result": None},
    {"index": 1, "type": "evaluate", "success": True, "result": "Example Domain"},
    {
        "index": 2,
        "type": "screenshot",
        "success": True,
        "screenshot_url": "https://alterlab.io/downloads/screenshots/a.png",
    },
    {"index": 3, "type": "wait_for", "success": False, "error": "timeout"},
]


@pytest.mark.parametrize(
    "action, expected",
    [
        (Actions.wait(milliseconds=1000), {"type": "wait", "milliseconds": 1000}),
        (Actions.wait(selector="#app"), {"type": "wait", "selector": "#app"}),
        (
            Actions.wait(milliseconds=5000, selector="#app"),
            {"type": "wait", "milliseconds": 5000, "selector": "#app"},
        ),
        (
            Actions.wait_for("#x"),
            {"type": "wait_for", "selector": "#x", "timeout": 10000},
        ),
        (
            Actions.wait_for("#x", timeout=2000),
            {"type": "wait_for", "selector": "#x", "timeout": 2000},
        ),
        (Actions.click("button.more"), {"type": "click", "selector": "button.more"}),
        (
            Actions.fill("input[name=q]", "shoes"),
            {"type": "fill", "selector": "input[name=q]", "value": "shoes"},
        ),
        (Actions.press("Enter"), {"type": "press", "key": "Enter"}),
        (Actions.scroll(), {"type": "scroll", "direction": "down", "amount": 1}),
        (
            Actions.scroll(direction="up", amount=3),
            {"type": "scroll", "direction": "up", "amount": 3},
        ),
        (
            Actions.infinite_scroll(),
            {"type": "infinite_scroll", "max_scrolls": 10, "delay": 1000},
        ),
        (
            Actions.infinite_scroll(max_scrolls=5, delay=500, end_selector=".end"),
            {
                "type": "infinite_scroll",
                "max_scrolls": 5,
                "delay": 500,
                "end_selector": ".end",
            },
        ),
        (Actions.screenshot(), {"type": "screenshot", "full_page": True}),
        (
            Actions.screenshot(full_page=False),
            {"type": "screenshot", "full_page": False},
        ),
        (
            Actions.evaluate("document.title"),
            {"type": "evaluate", "script": "document.title"},
        ),
        (Actions.dismiss_consent(), {"type": "dismiss_consent", "mode": "hide"}),
        (
            Actions.dismiss_consent("reject"),
            {"type": "dismiss_consent", "mode": "reject"},
        ),
    ],
)
def test_typed_actions_serialise_to_exact_api_json(action, expected):
    assert action.to_dict() == expected
    assert json.loads(json.dumps(action.to_dict())) == expected


def test_builders_return_typed_classes():
    assert isinstance(Actions.click("a"), ClickAction)
    assert isinstance(Actions.evaluate("1"), EvaluateAction)
    assert isinstance(Actions.wait(milliseconds=100), WaitAction)
    assert isinstance(Actions.dismiss_consent(), DismissConsentAction)
    assert Actions.click("a").type == "click"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Actions.wait(),
        lambda: Actions.wait(milliseconds=50),
        lambda: Actions.wait(milliseconds=30001),
        lambda: Actions.wait(selector="   "),
        lambda: Actions.wait_for("#x", timeout=999),
        lambda: Actions.click(""),
        lambda: Actions.click("a" * 501),
        lambda: Actions.fill("#q", "x" * 5001),
        lambda: Actions.press("k" * 51),
        lambda: Actions.scroll(direction="left"),
        lambda: Actions.scroll(amount=21),
        lambda: Actions.infinite_scroll(max_scrolls=51),
        lambda: Actions.infinite_scroll(delay=100),
        lambda: Actions.evaluate(""),
        lambda: Actions.evaluate("x" * 5121),
        lambda: Actions.dismiss_consent("close"),
    ],
)
def test_constraint_violations_raise_value_error(build):
    with pytest.raises(ValueError):
        build()


def _client(handler) -> AlterLab:
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_scrape_sends_typed_and_raw_actions_and_parses_sync_results():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json={"url": "https://example.com", "action_results": ACTION_RESULTS}
        )

    client = _client(handler)
    try:
        result = await client.scrape(
            "https://example.com",
            advanced=AdvancedOptions(render_js=True),
            actions=[
                Actions.click("button.more"),
                {"type": "evaluate", "script": "document.title"},
                Actions.screenshot(),
            ],
        )
    finally:
        await client.close()

    assert bodies[0]["advanced"]["actions"] == [
        {"type": "click", "selector": "button.more"},
        {"type": "evaluate", "script": "document.title"},
        {"type": "screenshot", "full_page": True},
    ]
    _assert_typed_results(result)


@pytest.mark.asyncio
async def test_polled_job_action_results_are_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1", "status": "pending"})
        assert request.url.path == "/api/v1/jobs/job-1"
        return httpx.Response(
            200,
            json={
                "job_id": "job-1",
                "status": "completed",
                "result": {
                    "url": "https://example.com",
                    "action_results": ACTION_RESULTS,
                },
            },
        )

    client = _client(handler)
    try:
        result = await client.scrape(
            "https://example.com",
            advanced=AdvancedOptions(render_js=True),
            actions=[Actions.click("button.more"), Actions.screenshot()],
            poll_interval=0.01,
        )
    finally:
        await client.close()

    _assert_typed_results(result)


@pytest.mark.asyncio
async def test_null_action_results_stay_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"url": "https://example.com", "action_results": None}
        )

    client = _client(handler)
    try:
        result = await client.scrape("https://example.com")
    finally:
        await client.close()

    assert result["action_results"] is None


@pytest.mark.asyncio
async def test_unsupported_action_item_raises_validation_error():
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    try:
        with pytest.raises(AlterLabValidationError, match=r"actions\[0\]"):
            await client.scrape(
                "https://example.com",
                advanced=AdvancedOptions(render_js=True),
                actions=["click"],
            )
    finally:
        await client.close()


def _assert_typed_results(result):
    results = result["action_results"]
    assert all(isinstance(r, ActionResult) for r in results)
    assert results == ACTION_RESULTS
    assert results[0].success is True and results[0]["success"] is True
    assert results[1].type == "evaluate" and results[1].result == "Example Domain"
    assert (
        results[2].screenshot_url == "https://alterlab.io/downloads/screenshots/a.png"
    )
    assert results[2].screenshot is None
    assert results[3].success is False and results[3].error == "timeout"
    assert results[3].index == 3


def test_scroll_into_view_serialises_and_validates():
    assert Actions.scroll_into_view("li.row", "start", "iframe#a").to_dict() == {
        "type": "scroll_into_view",
        "selector": "li.row",
        "block": "start",
        "frame": "iframe#a",
    }
    assert Actions.scroll_into_view("li").to_dict()["block"] == "center"
    with pytest.raises(ValueError):
        Actions.scroll_into_view("li", "middle")
