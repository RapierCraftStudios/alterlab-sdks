"""#38746: ActionResult.observation typing and observe passthrough."""

from alterlab import (
    ActionObservation,
    ActionResult,
    parse_action_results,
    serialize_actions,
)


def test_observation_wrapped():
    obs = {
        "verified": True,
        "readiness": "stable",
        "url": "https://x.test/a",
        "transitions": [{"to_url": "u"}],
        "diagnostics": ["x"],
    }
    r = ActionResult({"index": 0, "type": "click", "success": True, "observation": obs})
    o = r.observation
    assert isinstance(o, ActionObservation)
    assert o.verified is True and o.readiness == "stable"
    assert o.transitions == [{"to_url": "u"}] and o.diagnostics == ["x"]
    assert o.route is None and o.snapshot is None


def test_observation_absent_is_none():
    assert ActionResult({"index": 0}).observation is None
    assert ActionObservation({}).transitions == []


def test_parse_action_results_and_observe_passthrough():
    res = parse_action_results(
        {"action_results": [{"observation": {"verified": False}}]}
    )
    assert res["action_results"][0].observation.verified is False
    action = {"type": "click", "selector": "a", "observe": True}
    assert serialize_actions([action]) == [action]
