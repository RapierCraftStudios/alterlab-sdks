"""#38736: typed `download` action and `ActionResult.artifact`."""

import pytest

from alterlab import ActionResult, Actions, ArtifactMetadata, DownloadAction
from alterlab.actions import serialize_actions


def test_selector_download_serialises():
    assert Actions.download(
        selector="a.dl", max_bytes=10, frame="iframe#f"
    ).to_dict() == {
        "type": "download",
        "timeout_ms": 15000,
        "selector": "a.dl",
        "max_bytes": 10,
        "frame": "iframe#f",
    }


def test_url_download_serialises_and_passes_through():
    action = Actions.download(url="https://example.com/f.pdf", timeout_ms=2000)
    assert serialize_actions([action, {"type": "wait", "milliseconds": 100}]) == [
        {"type": "download", "timeout_ms": 2000, "url": "https://example.com/f.pdf"},
        {"type": "wait", "milliseconds": 100},
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"selector": "a", "url": "https://x.io/f"},
        {"url": "ftp://x.io/f"},
        {"url": "https://x.io/f", "frame": "iframe"},
        {"selector": "a", "timeout_ms": 999},
        {"selector": "a", "timeout_ms": 30001},
        {"selector": "a", "max_bytes": 0},
        {"selector": "a", "max_bytes": 100 * 1024 * 1024 + 1},
    ],
)
def test_invalid_download_rejected(kwargs):
    with pytest.raises(ValueError):
        DownloadAction(**kwargs)


def test_action_result_artifact_typed():
    meta = {
        "artifact_id": "art_1",
        "filename": "f.pdf",
        "media_type": "application/pdf",
        "size_bytes": 5,
        "sha256": "ab",
        "status": "stored",
        "expires_at": 1.5,
    }
    artifact = ActionResult(
        {"index": 0, "type": "download", "success": True, "artifact": meta}
    ).artifact
    assert isinstance(artifact, ArtifactMetadata)
    assert (artifact.artifact_id, artifact.size_bytes, artifact.expires_at) == (
        "art_1",
        5,
        1.5,
    )
    assert ActionResult({"index": 0}).artifact is None
