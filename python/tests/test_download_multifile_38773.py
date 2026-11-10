"""#38773: multi-file download options, scan_status, artifacts/bundle accessors."""

import pytest

from alterlab import ActionResult, Actions, ArtifactMetadata, DownloadAction


def test_multifile_options_serialise():
    assert Actions.download(
        selector="a.dl", max_files=3, max_total_bytes=500, quiet_ms=200, bundle="zip"
    ).to_dict() == {
        "type": "download",
        "timeout_ms": 15000,
        "selector": "a.dl",
        "max_files": 3,
        "max_total_bytes": 500,
        "quiet_ms": 200,
        "bundle": "zip",
    }


def test_defaults_are_omitted():
    assert "max_files" not in Actions.download(selector="a").to_dict()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_files": 0},
        {"max_files": 11},
        {"max_files": 2, "quiet_ms": 99},
        {"max_files": 2, "quiet_ms": 10001},
        {"max_files": 2, "max_total_bytes": 0},
        {"max_files": 2, "bundle": "tar"},
        {"bundle": "zip"},
        {"max_total_bytes": 10},
    ],
)
def test_invalid_multifile_rejected(kwargs):
    with pytest.raises(ValueError):
        DownloadAction(selector="a", **kwargs)


def test_result_artifacts_bundle_scan_status():
    meta = {"artifact_id": "a1", "scan_status": "quarantined"}
    r = ActionResult(
        {"index": 0, "artifacts": [meta], "bundle": {"artifact_id": "z", "scan_status": "clean"}}
    )
    assert isinstance(r.artifacts[0], ArtifactMetadata)
    assert r.artifacts[0].scan_status == "quarantined"
    assert r.bundle.artifact_id == "z"
    assert ActionResult({"index": 0}).artifacts is None
    assert ActionResult({"index": 0}).bundle is None
