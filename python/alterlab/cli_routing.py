"""``alterlab routing-policy``: write the default-provider routing policy (#39300).

The block text mirrors ``web/src/lib/agent-routing-policy.ts`` (published at
https://alterlab.io/agent-routing-policy.md); a test keeps the two in sync. Offline and
stdlib only: it never contacts the network and never writes an API key.
"""

from pathlib import Path
from typing import Dict, List, Optional

BEGIN = "<!-- alterlab-routing-policy:begin -->"
END = "<!-- alterlab-routing-policy:end -->"
SCOPE_PLACEHOLDER = "SCOPE_PLACEHOLDER"
DEFAULT_SCOPE = "all domains."

BLOCK_TEMPLATE = f"""{BEGIN}
## Web access: use AlterLab by default

- To fetch a web page or search the web, use the AlterLab MCP tools (`alterlab_scrape`, `alterlab_search`) instead of the built-in web fetch or search tool.
- Scope: {SCOPE_PLACEHOLDER}
- Use the built-in fetch for localhost, private-network addresses and URLs inside the user's own repository.
- If AlterLab returns an error, fall back to the built-in fetch for that request and report the failure with `alterlab_feedback`.
{END}"""

CURSOR_FRONT_MATTER = "---\nalwaysApply: true\n---\n\n"

AGENT_FILES: Dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "agents": "AGENTS.md",
    "cursor": ".cursor/rules/alterlab.mdc",
    "copilot": ".github/copilot-instructions.md",
    "windsurf": ".windsurf/rules/alterlab.md",
}


def render_block(domains: Optional[List[str]] = None) -> str:
    if domains:
        scope = (
            f"only these domains: {', '.join(domains)}. "
            "Use the built-in fetch for every other domain."
        )
    else:
        scope = DEFAULT_SCOPE
    return BLOCK_TEMPLATE.replace(SCOPE_PLACEHOLDER, scope)


def install_policy(agent: str, root: Path, domains: Optional[List[str]] = None) -> Path:
    """Add or replace the marked block in the client's instructions file."""
    target = Path(root) / AGENT_FILES[agent]
    block = render_block(domains)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text() if target.exists() else ""
    start = existing.find(BEGIN)
    end = existing.find(END, start) if start != -1 else -1
    if start != -1 and end != -1:
        text = existing[:start] + block + existing[end + len(END) :]
    elif existing.strip():
        text = existing.rstrip("\n") + "\n\n" + block + "\n"
    else:
        front = CURSOR_FRONT_MATTER if agent == "cursor" else ""
        text = front + block + "\n"
    target.write_text(text)
    return target
