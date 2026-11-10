"""#38768: download action integration_id/key_template and ActionResult.delivery."""

import pytest

from alterlab import ActionResult, Actions, ArtifactDelivery, DownloadAction

INTEGRATION = "123e4567-e89b-12d3-a456-426614174000"


def test_delivery_fields_serialise_only_when_set():
    assert "integration_id" not in Actions.download(selector="a").to_dict()
    data = Actions.download(
        selector="a", integration_id=INTEGRATION, key_template="x/{job_id}/{filename}"
    ).to_dict()
    assert data["integration_id"] == INTEGRATION
    assert data["key_template"] == "x/{job_id}/{filename}"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"integration_id": "nope"},
        {"key_template": "a/{filename}"},
        {"integration_id": INTEGRATION, "key_template": "../x"},
        {"integration_id": INTEGRATION, "key_template": "a b"},
        {"integration_id": INTEGRATION, "key_template": "{bad}"},
        {"integration_id": INTEGRATION, "key_template": "a" * 201},
    ],
)
def test_invalid_delivery_rejected(kwargs):
    with pytest.raises(ValueError):
        DownloadAction(selector="a", **kwargs)


def test_action_result_delivery_typed():
    raw = {"integration_id": INTEGRATION, "status": "delivered", "key": "k", "bytes": 3}
    d = ActionResult({"index": 0, "delivery": raw}).delivery
    assert isinstance(d, ArtifactDelivery)
    assert (d.integration_id, d.status, d.key, d.bytes, d.error) == (
        INTEGRATION,
        "delivered",
        "k",
        3,
        None,
    )
    assert ActionResult({"index": 0}).delivery is None
