"""#36692: ``frame`` on typed selector actions and the ``snapshot`` action."""

import pytest

from alterlab import ActionResult, Actions, SnapshotAction, serialize_actions


@pytest.mark.parametrize(
    "build, expected",
    [
        (
            lambda f: Actions.wait(selector="#r", frame=f),
            {"type": "wait", "selector": "#r"},
        ),
        (
            lambda f: Actions.wait_for("#r", frame=f),
            {"type": "wait_for", "selector": "#r", "timeout": 10000},
        ),
        (
            lambda f: Actions.click("#pay", frame=f),
            {"type": "click", "selector": "#pay"},
        ),
        (
            lambda f: Actions.fill("#c", "4242", frame=f),
            {"type": "fill", "selector": "#c", "value": "4242"},
        ),
        (
            lambda f: Actions.press("Enter", "#q", frame=f),
            {"type": "press", "key": "Enter", "selector": "#q"},
        ),
        (
            lambda f: Actions.select("#s", value="m", frame=f),
            {"type": "select", "selector": "#s", "value": "m"},
        ),
        (lambda f: Actions.hover("#m", frame=f), {"type": "hover", "selector": "#m"}),
        (
            lambda f: Actions.click_text("Pay", frame=f),
            {"type": "click_text", "text": "Pay", "exact": False},
        ),
        (
            lambda f: Actions.extract(".p", frame=f),
            {"type": "extract", "selector": ".p"},
        ),
        (lambda f: Actions.check("#t", frame=f), {"type": "check", "selector": "#t"}),
        (
            lambda f: Actions.uncheck("#t", frame=f),
            {"type": "uncheck", "selector": "#t"},
        ),
    ],
)
def test_frame_is_emitted_only_when_set(build, expected):
    assert build(None).to_dict() == expected
    assert build("iframe#a").to_dict() == {**expected, "frame": "iframe#a"}
    assert build(("#a", "#b")).to_dict() == {**expected, "frame": ["#a", "#b"]}


@pytest.mark.parametrize(
    "frame", [[], ["#a", "#b", "#c", "#d"], " ", ["#a", ""], "x" * 501]
)
def test_invalid_frame_raises(frame):
    with pytest.raises(ValueError):
        Actions.click("#pay", frame=frame)


def test_frame_requires_selector_on_wait_and_press():
    with pytest.raises(ValueError):
        Actions.wait(milliseconds=500, frame="#f")
    with pytest.raises(ValueError):
        Actions.press("Enter", frame="#f")


def test_snapshot_builder_and_validation():
    assert Actions.snapshot().to_dict() == {"type": "snapshot", "format": "html"}
    assert Actions.snapshot("markdown").to_dict() == {
        "type": "snapshot",
        "format": "markdown",
    }
    assert isinstance(Actions.snapshot(), SnapshotAction)
    with pytest.raises(ValueError):
        Actions.snapshot("pdf")  # type: ignore[arg-type]


def test_snapshot_serializes_in_action_lists():
    assert serialize_actions([Actions.snapshot(), Actions.click("#a")]) == [
        {"type": "snapshot", "format": "html"},
        {"type": "click", "selector": "#a"},
    ]


def test_action_result_snapshot_url():
    assert ActionResult({"snapshot_url": "https://s/x.md.txt"}).snapshot_url == (
        "https://s/x.md.txt"
    )
    assert ActionResult({}).snapshot_url is None
