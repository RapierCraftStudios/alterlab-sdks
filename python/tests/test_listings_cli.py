"""#38848: ``alterlab listings`` init/validate/test/run/publish with mocked HTTP."""

import json

import httpx
import pytest

from alterlab import cli, listings


def _mock(monkeypatch, handler):
    monkeypatch.setattr(
        listings,
        "_http",
        lambda: httpx.Client(
            base_url="https://api.alterlab.io", transport=httpx.MockTransport(handler)
        ),
    )


def _init(tmp_path, capsys, slug="acme-prices"):
    assert cli.main(["listings", "--dir", str(tmp_path), "init", slug]) == 0
    capsys.readouterr()
    return tmp_path / slug


def test_init_scaffolds_a_valid_two_step_manifest(tmp_path, capsys):
    directory = _init(tmp_path, capsys)
    manifest = json.loads((directory / "manifest.json").read_text())
    kinds = [s["kind"] for s in manifest["steps"]]
    assert kinds == ["fetch", "parse", "transform"]
    assert listings.validate_manifest(manifest) == []
    assert cli.main(["listings", "--dir", str(tmp_path), "init", "acme-prices"]) == 1  # no clobber


def test_init_rejects_a_bad_slug(tmp_path, capsys):
    assert cli.main(["listings", "--dir", str(tmp_path), "init", "Bad Slug"]) == 1


def test_validate_reports_local_errors(tmp_path, capsys):
    directory = _init(tmp_path, capsys)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["login_required"] = True
    manifest["steps"][0]["kind"] = "parse"
    del manifest["pricing"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert cli.main(["listings", "--dir", str(directory), "validate"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is False
    joined = " ".join(out["errors"])
    assert "missing field: pricing" in joined and "login_required" in joined
    assert "first step" in joined


def test_test_creates_the_draft_then_replaces_it_and_exits_on_result(tmp_path, capsys, monkeypatch):
    directory = _init(tmp_path, capsys)
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/v1/listings/drafts":
            return httpx.Response(201, json={"id": "d1"})
        if request.url.path.endswith("/test"):
            return httpx.Response(200, json={"passed": False, "results": [{"index": 0}]})
        return httpx.Response(200, json={"id": "d1"})

    _mock(monkeypatch, handler)
    assert cli.main(["listings", "--dir", str(directory), "test"]) == 1  # failing test inputs
    assert json.loads(capsys.readouterr().out)["passed"] is False
    assert cli.main(["listings", "--dir", str(directory), "test"]) == 1
    assert seen == [
        ("POST", "/api/v1/listings/drafts"),
        ("POST", "/api/v1/listings/drafts/d1/test"),
        ("PUT", "/api/v1/listings/drafts/d1"),
        ("POST", "/api/v1/listings/drafts/d1/test"),
    ]


def test_test_refuses_an_invalid_manifest_without_http(tmp_path, capsys, monkeypatch):
    directory = _init(tmp_path, capsys)
    (directory / "manifest.json").write_text("{}")
    _mock(monkeypatch, lambda r: pytest.fail("no request expected"))
    assert cli.main(["listings", "--dir", str(directory), "test"]) == 1


def test_publish_surfaces_the_server_failure_reasons(tmp_path, capsys, monkeypatch):
    directory = _init(tmp_path, capsys)
    (directory / ".listing-draft.json").write_text(json.dumps({"draft_id": "d1"}))
    detail = {"code": "test_inputs_not_passing", "failures": [{"index": 0, "reason": "timeout"}]}

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "d1"})
        return httpx.Response(422, json={"detail": detail})

    _mock(monkeypatch, handler)
    assert cli.main(["listings", "--dir", str(directory), "publish"]) == 1
    err = capsys.readouterr().err
    assert "422" in err and "test_inputs_not_passing" in err and "timeout" in err


def test_publish_success_prints_the_pending_review_version(tmp_path, capsys, monkeypatch):
    directory = _init(tmp_path, capsys)
    (directory / ".listing-draft.json").write_text(json.dumps({"draft_id": "d1"}))

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "d1"})
        assert request.url.path == "/api/v1/listings/drafts/d1/publish"
        return httpx.Response(201, json={"slug": "acme-prices", "status": "pending_review"})

    _mock(monkeypatch, handler)
    assert cli.main(["listings", "--dir", str(directory), "publish"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pending_review"


def test_run_posts_input_and_max_results(capsys, monkeypatch):
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "completed", "results": [{"a": 1}]})

    _mock(monkeypatch, handler)
    code = cli.main(
        ["listings", "run", "acme-prices", "--input", '{"query":"x"}', "--max-results", "5"]
    )
    assert code == 0
    assert captured == {
        "path": "/api/v1/listings/acme-prices/run",
        "params": {"wait": "true"},
        "body": {"input": {"query": "x"}, "max_results": 5},
    }
    assert json.loads(capsys.readouterr().out)["results"] == [{"a": 1}]


def test_run_rejects_non_json_input(capsys):
    assert cli.main(["listings", "run", "acme-prices", "--input", "{nope"]) == 1
