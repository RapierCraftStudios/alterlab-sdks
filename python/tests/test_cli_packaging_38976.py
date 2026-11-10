"""#38976: Homebrew formula template and npx shim packaging for the alterlab CLI."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RENDER = ROOT / "packaging" / "homebrew" / "render.py"
WORKFLOW = ROOT / ".github" / "workflows" / "publish-sdks.yml"


def _load_render():
    spec = importlib.util.spec_from_file_location("hb_render", RENDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_fills_url_and_sha256():
    doc = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://x/w.whl",
                "digests": {"sha256": "w"},
            },
            {
                "packagetype": "sdist",
                "url": "https://x/alterlab-1.tar.gz",
                "digests": {"sha256": "ab12"},
            },
        ]
    }
    out = _load_render().render_formula(doc)
    assert 'url "https://x/alterlab-1.tar.gz"' in out
    assert 'sha256 "ab12"' in out
    assert "@URL@" not in out and "@SHA256@" not in out


def test_render_includes_dependency_resources():
    def sd(n):
        return {"urls": [{"packagetype": "sdist", "url": f"https://x/{n}.tgz",
                          "digests": {"sha256": n}}],
                "info": {"requires_dist": ["h11>=1; extra == 'x'"] if n == "httpx" else None}}

    root = sd("alterlab")
    root["info"]["requires_dist"] = ["httpx>=0.25", "tomli; python_version < '3.11'"]
    out = _load_render().render_formula(root, fetch=sd)
    assert 'resource "httpx" do' in out and 'url "https://x/httpx.tgz"' in out
    assert "tomli" not in out and "h11" not in out
    assert "virtualenv_install_with_resources" in out and "@RESOURCES@" not in out


def test_render_requires_sdist():
    with pytest.raises(ValueError):
        _load_render().render_formula({"urls": [], "info": {}})


def test_npx_shim_package():
    pkg = json.loads((ROOT / "sdk" / "cli-npx" / "package.json").read_text())
    assert pkg["license"] == "MIT"
    assert pkg["bin"]["alterlab"] == "bin/alterlab.js"
    assert (ROOT / "sdk" / "cli-npx" / pkg["bin"]["alterlab"]).is_file()


def test_workflow_has_cli_job_and_pinned_actions():
    text = WORKFLOW.read_text()
    assert "publish-cli-npx:" in text
    assert "- cli\n" in text
    assert "packaging/homebrew/render.py" in text
    for line in text.splitlines():
        if "uses:" in line:
            assert "@" in line and len(line.split("@")[1].split()[0]) == 40, line
