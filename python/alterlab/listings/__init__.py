"""``alterlab listings init|validate|test|run|publish`` for Data Marketplace sellers (#38848).

A listing lives in a directory holding ``manifest.json`` and ``.listing-draft.json`` (the draft
id once ``test`` or ``publish`` has created it). ``validate`` runs locally and mirrors the
cheap structural rules of the server validator (``shared/marketplace/manifest.py``); the server
stays the authority and returns field errors on 422. ``test`` saves the manifest as a draft and
runs every ``test_inputs`` entry on live fetches (you pay base cost, no markup). ``publish``
is refused by the server until the last test covered this exact manifest and every input passed.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..cli_auth import load_key
from ..client import AlterLabError

MANIFEST_FILE = "manifest.json"
DRAFT_FILE = ".listing-draft.json"
DEFAULT_BASE_URL = "https://api.alterlab.io"
STEP_KINDS = {
    "fetch",
    "parse",
    "filter",
    "dedupe",
    "transform",
    "map_entity",
    "call_listing",
}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_REQUIRED = (
    "slug",
    "version",
    "title",
    "summary",
    "category",
    "data_class",
    "login_required",
    "input_schema",
    "output_schema",
    "steps",
    "pricing",
    "test_inputs",
    "owner",
)


def scaffold(slug: str, owner_id: str = "creator") -> Dict[str, Any]:
    """A two-step starter: fetch a page, parse rows with CSS, then a sandboxed transform."""
    return {
        "slug": slug,
        "version": "1.0.0",
        "title": slug.replace("-", " ").title(),
        "summary": "Describe what each result contains",
        "category": "general",
        "data_class": "business",
        "login_required": False,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
        },
        "steps": [
            {"kind": "fetch", "url_templates": ["https://example.com/search?q={query}"]},
            {
                "kind": "parse",
                "selector_type": "css",
                "selector": ".result",
                "fields": {"name": ".title", "url": "a@href"},
            },
            {
                "kind": "transform",
                "language": "python",
                "code": (
                    "rows = list(input.values())[0]\n"
                    "rows = rows.get('records') or rows.get('results') or []\n"
                    "result = [{'name': r['name'].strip(), 'url': r['url']} for r in rows]"
                ),
            },
        ],
        "pricing": {"markup_microcents_per_result": 0},
        "test_inputs": [
            {"input": {"query": "example"}, "min_records": 1, "required_fields": ["name", "url"]}
        ],
        "owner": {"kind": "creator", "id": owner_id},
    }


def validate_manifest(manifest: Any) -> List[str]:
    """Structural problems found locally; empty means the manifest is ready for ``test``."""
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    errors = [f"missing field: {k}" for k in _REQUIRED if k not in manifest]
    slug = manifest.get("slug")
    if slug is not None and not (isinstance(slug, str) and _SLUG_RE.match(slug)):
        errors.append("slug must be lowercase kebab-case")
    version = manifest.get("version")
    if version is not None and not (isinstance(version, str) and _SEMVER_RE.match(version)):
        errors.append("version must be semver, e.g. 1.0.0")
    if manifest.get("login_required"):
        errors.append("login_required listings are not allowed")
    steps = manifest.get("steps")
    if steps is not None:
        if not isinstance(steps, list) or not steps:
            errors.append("steps must be a non-empty list")
        else:
            for i, step in enumerate(steps):
                kind = step.get("kind") if isinstance(step, dict) else None
                if kind not in STEP_KINDS:
                    errors.append(f"steps[{i}]: unknown kind {kind!r}")
            first = steps[0].get("kind") if isinstance(steps[0], dict) else None
            if first not in ("fetch", "call_listing"):
                errors.append("the first step must be 'fetch' or 'call_listing'")
            for i, step in enumerate(steps):
                if isinstance(step, dict) and step.get("kind") == "transform":
                    if not step.get("code") or len(step["code"]) > 20000:
                        errors.append(f"steps[{i}]: transform code must be 1-20000 characters")
    tests = manifest.get("test_inputs")
    if tests is not None:
        if not isinstance(tests, list) or not tests:
            errors.append("test_inputs must be a non-empty list")
        else:
            for i, entry in enumerate(tests):
                if not isinstance(entry, dict) or not all(
                    k in entry for k in ("input", "min_records", "required_fields")
                ):
                    errors.append(f"test_inputs[{i}]: needs input, min_records, required_fields")
    return errors


def _http() -> httpx.Client:
    key = load_key()
    if not key:
        raise AlterLabError("not logged in: run `alterlab login` or set ALTERLAB_API_KEY")
    return httpx.Client(
        base_url=os.environ.get("ALTERLAB_BASE_URL", DEFAULT_BASE_URL),
        headers={"X-API-Key": key, "User-Agent": "alterlab-cli"},
        timeout=120,
    )


def _check(response: httpx.Response) -> Dict[str, Any]:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise AlterLabError(f"{response.status_code}: {json.dumps(detail, default=str)}")
    return response.json() if response.content else {}


def _load(directory: Path) -> Dict[str, Any]:
    path = directory / MANIFEST_FILE
    if not path.exists():
        raise AlterLabError(f"{path} not found: run `alterlab listings init <slug>`")
    try:
        return json.loads(path.read_text())
    except ValueError as exc:
        raise AlterLabError(f"{path} is not valid JSON: {exc}")


def _draft_state(directory: Path) -> Dict[str, Any]:
    path = directory / DRAFT_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def init(slug: str, directory: Path) -> Path:
    if not _SLUG_RE.match(slug):
        raise AlterLabError("slug must be lowercase kebab-case")
    path = directory / MANIFEST_FILE
    if path.exists():
        raise AlterLabError(f"{path} already exists")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scaffold(slug), indent=2) + "\n")
    return path


def validate(directory: Path) -> List[str]:
    return validate_manifest(_load(directory))


def sync_draft(client: httpx.Client, directory: Path, manifest: Dict[str, Any]) -> str:
    """Create the draft on first use, otherwise replace its manifest; returns the draft id."""
    state = _draft_state(directory)
    draft_id: Optional[str] = state.get("draft_id")
    if draft_id:
        _check(client.put(f"/api/v1/listings/drafts/{draft_id}", json={"manifest": manifest}))
        return draft_id
    created = _check(client.post("/api/v1/listings/drafts", json={"manifest": manifest}))
    (directory / DRAFT_FILE).write_text(json.dumps({"draft_id": created["id"]}) + "\n")
    return created["id"]


def test(directory: Path) -> Dict[str, Any]:
    manifest = _load(directory)
    errors = validate_manifest(manifest)
    if errors:
        raise AlterLabError("manifest invalid: " + "; ".join(errors))
    with _http() as client:
        draft_id = sync_draft(client, directory, manifest)
        return _check(client.post(f"/api/v1/listings/drafts/{draft_id}/test"))


def run(slug: str, inputs: Dict[str, Any], max_results: Optional[int] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"input": inputs}
    if max_results is not None:
        body["max_results"] = max_results
    with _http() as client:
        return _check(
            client.post(f"/api/v1/listings/{slug}/run", params={"wait": "true"}, json=body)
        )


def publish(directory: Path) -> Dict[str, Any]:
    manifest = _load(directory)
    with _http() as client:
        draft_id = sync_draft(client, directory, manifest)
        return _check(client.post(f"/api/v1/listings/drafts/{draft_id}/publish"))


def add_parser(sub) -> None:
    """Register ``alterlab listings`` on the CLI's subparsers."""
    lst = sub.add_parser("listings", help="Build, test and publish Data Marketplace listings")
    cmds = lst.add_subparsers(dest="listings_command", required=True)
    p = cmds.add_parser("init", help="Scaffold manifest.json")
    p.add_argument("slug")
    for name, helptext in (
        ("validate", "Check manifest.json locally"),
        ("test", "Run every test input on live fetches (base cost, no markup)"),
        ("publish", "Publish the tested draft for review"),
    ):
        cmds.add_parser(name, help=helptext)
    p = cmds.add_parser("run", help="Run a published listing")
    p.add_argument("slug")
    p.add_argument("--input", default="{}", help="JSON input matching the input_schema")
    p.add_argument("--max-results", type=int)
    lst.add_argument("--dir", default=".", help="Directory holding manifest.json")


def dispatch(args, emit) -> int:
    directory = Path(args.dir)
    cmd = args.listings_command
    if cmd == "init":
        emit({"created": str(init(args.slug, directory / args.slug))})
        return 0
    if cmd == "validate":
        errors = validate(directory)
        emit({"valid": not errors, "errors": errors})
        return 0 if not errors else 1
    if cmd == "test":
        result = test(directory)
        emit(result)
        return 0 if result.get("passed") else 1
    if cmd == "run":
        try:
            inputs = json.loads(args.input)
        except ValueError as exc:
            raise AlterLabError(f"--input is not valid JSON: {exc}")
        emit(run(args.slug, inputs, args.max_results))
        return 0
    emit(publish(directory))
    return 0
