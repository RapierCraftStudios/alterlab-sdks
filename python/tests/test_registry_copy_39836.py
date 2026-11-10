"""Registry/README copy rules (#39836): no prohibited terms, short one-liners, prices from shared/pricing.py."""

import json
import re
import subprocess
from pathlib import Path

import pytest

SDK = Path(__file__).resolve().parents[2]
REPO = SDK.parent
PROHIBITED = re.compile(r"anti-bot[ -]bypass|\bstealth\b", re.IGNORECASE)
COPY_FILES = [
    SDK / "python" / "README.md",
    SDK / "node" / "README.md",
    SDK / "python" / "pyproject.toml",
    SDK / "node" / "package.json",
    SDK / "llama-index-readers-alterlab" / "README.md",
    SDK / "ai-sdk-alterlab" / "README.md",
    SDK / "n8n" / "README.md",
]


def _python_description() -> str:
    m = re.search(r'^description = "(.*)"$', (SDK / "python/pyproject.toml").read_text(), re.M)
    assert m
    return m.group(1)


def _node_description() -> str:
    return json.loads((SDK / "node/package.json").read_text())["description"]


def test_no_prohibited_terms_in_sdk_copy():
    for path in COPY_FILES:
        if path.exists():
            assert not PROHIBITED.search(path.read_text()), path


@pytest.mark.parametrize("get", [_python_description, _node_description])
def test_registry_description_is_short_one_liner(get):
    desc = get()
    assert 0 < len(desc) < 200
    assert "\n" not in desc
    assert not PROHIBITED.search(desc)


def test_readme_tier_prices_match_shared_pricing():
    pricing = REPO / "shared" / "pricing.py"
    if not pricing.exists():
        pytest.skip("shared/pricing.py not available")
    ns: dict = {}
    src = pricing.read_text()
    block = re.search(r"TIER_MICROCENTS: Dict\[str, int\] = \{.*?\n\}", src, re.S)
    assert block
    exec(
        "from typing import Dict\n" + block.group(0), ns
    )  # noqa: S102 - literal dict from repo file
    micro = ns["TIER_MICROCENTS"]
    rows = re.findall(
        r"^\| ([1-5]) \| ([^|]+) \| \$([0-9.]+) \| ([0-9,]+) \|$",
        (SDK / "python/README.md").read_text(),
        re.M,
    )
    assert len(rows) == 5
    for tier, name, price, per_dollar in rows:
        assert float(price) == micro[tier] / 1_000_000
        assert int(per_dollar.replace(",", "")) == int(1_000_000 / micro[tier])
        assert not re.search(r"stealth|captcha|curl", name, re.I)


def test_version_sites_agree():
    py = re.search(r'^version = "(.*)"', (SDK / "python/pyproject.toml").read_text(), re.M).group(1)
    init = re.search(
        r'__version__ = "(.*)"', (SDK / "python/alterlab/__init__.py").read_text()
    ).group(1)
    client = re.search(
        r'_SDK_VERSION = "(.*)"', (SDK / "python/alterlab/client.py").read_text()
    ).group(1)
    assert py == init == client
    node = json.loads((SDK / "node/package.json").read_text())["version"]
    assert f'SDK_VERSION = "{node}"' in (SDK / "node/src/index.ts").read_text()
