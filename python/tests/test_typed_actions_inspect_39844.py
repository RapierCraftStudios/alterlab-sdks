"""#39844: inspect action and element_map result field (API InspectAction mirror)."""

import pytest

from alterlab import ActionResult, Actions, InspectAction, serialize_actions


def test_default_serialises():
    assert Actions.inspect().to_dict() == {"type": "inspect", "max_elements": 200}


def test_custom_max_elements():
    action = Actions.inspect(max_elements=500)
    assert isinstance(action, InspectAction)
    assert serialize_actions([action]) == [{"type": "inspect", "max_elements": 500}]


@pytest.mark.parametrize("value", [0, 501, -1, True, "5", 1.5])
def test_invalid_max_elements_rejected(value):
    with pytest.raises(ValueError):
        Actions.inspect(max_elements=value)


def test_result_accessors():
    result = ActionResult(
        {"index": 0, "type": "inspect", "element_map": {"total": 1}, "truncated": True}
    )
    assert result.element_map == {"total": 1}
    assert result.truncated is True
    empty = ActionResult({"index": 0})
    assert empty.element_map is None and empty.truncated is None
