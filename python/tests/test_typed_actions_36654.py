"""Typed builders for the #36654 browser actions serialise to the API's JSON."""

import pytest

from alterlab import (
    Actions,
    CheckAction,
    ClickTextAction,
    ExtractAction,
    HoverAction,
    SelectAction,
    UncheckAction,
    WaitEventAction,
    serialize_actions,
)


@pytest.mark.parametrize(
    "action, expected",
    [
        (
            Actions.select("select#size", label="M"),
            {"type": "select", "selector": "select#size", "label": "M"},
        ),
        (
            Actions.select("select#size", value="m"),
            {"type": "select", "selector": "select#size", "value": "m"},
        ),
        (Actions.hover(".menu"), {"type": "hover", "selector": ".menu"}),
        (
            Actions.click_text("Load more"),
            {"type": "click_text", "text": "Load more", "exact": False},
        ),
        (
            Actions.click_text("Next", exact=True),
            {"type": "click_text", "text": "Next", "exact": True},
        ),
        (Actions.extract("span.price"), {"type": "extract", "selector": "span.price"}),
        (
            Actions.extract("//a[@id='x']", attribute="href"),
            {"type": "extract", "selector": "//a[@id='x']", "attribute": "href"},
        ),
        (Actions.check("#tos"), {"type": "check", "selector": "#tos"}),
        (Actions.uncheck("#news"), {"type": "uncheck", "selector": "#news"}),
        (
            Actions.wait_event(),
            {"type": "wait_event", "event": "load", "timeout": 10000},
        ),
        (
            Actions.wait_event("networkidle", timeout=5000),
            {"type": "wait_event", "event": "networkidle", "timeout": 5000},
        ),
        (
            Actions.wait_for(".spinner", state="hidden"),
            {
                "type": "wait_for",
                "selector": ".spinner",
                "timeout": 10000,
                "state": "hidden",
            },
        ),
        (
            Actions.press("Enter", selector="input[name=q]"),
            {"type": "press", "key": "Enter", "selector": "input[name=q]"},
        ),
    ],
)
def test_new_actions_serialise_to_exact_api_json(action, expected):
    assert action.to_dict() == expected
    assert serialize_actions([action]) == [expected]


def test_builders_return_typed_classes():
    assert isinstance(Actions.select("s", label="a"), SelectAction)
    assert isinstance(Actions.hover("a"), HoverAction)
    assert isinstance(Actions.click_text("a"), ClickTextAction)
    assert isinstance(Actions.extract("a"), ExtractAction)
    assert isinstance(Actions.check("a"), CheckAction)
    assert isinstance(Actions.uncheck("a"), UncheckAction)
    assert isinstance(Actions.wait_event(), WaitEventAction)


@pytest.mark.parametrize(
    "build",
    [
        lambda: Actions.select("s"),
        lambda: Actions.select("s", value="a", label="b"),
        lambda: Actions.select(" ", label="a"),
        lambda: Actions.hover(""),
        lambda: Actions.click_text("  "),
        lambda: Actions.extract("a", attribute="x" * 101),
        lambda: Actions.check("a" * 501),
        lambda: Actions.wait_event("idle"),
        lambda: Actions.wait_event(timeout=999),
        lambda: Actions.wait_for("#x", state="gone"),
        lambda: Actions.press("Enter", selector=""),
    ],
)
def test_constraint_violations_raise_value_error(build):
    with pytest.raises(ValueError):
        build()
