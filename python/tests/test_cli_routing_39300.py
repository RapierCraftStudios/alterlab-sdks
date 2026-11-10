"""#39300: ``alterlab routing-policy`` writes the routing policy idempotently."""

import re
from pathlib import Path

import pytest

from alterlab import cli, cli_routing


def _run(tmp_path, *extra):
    return cli.main(["routing-policy", "--dir", str(tmp_path), *extra])


def test_creates_file_with_block(tmp_path):
    assert _run(tmp_path) == 0
    text = (tmp_path / "CLAUDE.md").read_text()
    assert cli_routing.BEGIN in text and "Scope: all domains." in text
    assert "SCOPE_PLACEHOLDER" not in text


def test_appends_preserving_existing_and_is_idempotent(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Mine\n\nkeep me\n")
    _run(tmp_path)
    first = (tmp_path / "CLAUDE.md").read_text()
    _run(tmp_path)
    second = (tmp_path / "CLAUDE.md").read_text()
    assert first == second
    assert first.startswith("# Mine\n\nkeep me\n")
    assert first.count(cli_routing.BEGIN) == 1


def test_domains_replace_block_in_place(tmp_path):
    (tmp_path / "AGENTS.md").write_text("top\n")
    _run(tmp_path, "--agent", "codex")
    _run(tmp_path, "--agent", "codex", "--domains", "a.com, b.org")
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.count(cli_routing.BEGIN) == 1 and text.startswith("top\n")
    assert "only these domains: a.com, b.org. Use the built-in fetch for every other domain." in text
    assert "all domains." not in text


def test_cursor_front_matter_only_on_new_file(tmp_path):
    _run(tmp_path, "--agent", "cursor")
    text = (tmp_path / ".cursor/rules/alterlab.mdc").read_text()
    assert text.startswith("---\nalwaysApply: true\n---\n")
    _run(tmp_path, "--agent", "cursor")
    assert (tmp_path / ".cursor/rules/alterlab.mdc").read_text() == text


@pytest.mark.parametrize("agent,path", sorted(cli_routing.AGENT_FILES.items()))
def test_every_agent_path(tmp_path, agent, path):
    _run(tmp_path, "--agent", agent)
    assert (tmp_path / path).is_file()


def test_never_writes_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_SECRET")
    _run(tmp_path)
    assert "sk_live_SECRET" not in (tmp_path / "CLAUDE.md").read_text()


def test_block_matches_published_typescript_source():
    ts = Path(__file__).resolve().parents[3] / "web/src/lib/agent-routing-policy.ts"
    if not ts.exists():
        pytest.skip("web source not available")
    src = ts.read_text()
    body = re.search(r"ROUTING_POLICY_BLOCK = `(.*?)`;", src, re.S).group(1)
    body = body.replace("${ROUTING_POLICY_BEGIN}", cli_routing.BEGIN)
    body = body.replace("${ROUTING_POLICY_END}", cli_routing.END).replace("\\`", "`")
    assert body == cli_routing.BLOCK_TEMPLATE
