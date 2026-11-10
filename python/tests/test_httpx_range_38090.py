"""#38090: the declared httpx range must admit modern httpx, not just 0.25.x."""
import re
from pathlib import Path

from packaging.specifiers import SpecifierSet

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _httpx_spec() -> SpecifierSet:
    m = re.search(r'^httpx\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
    assert m, "httpx dependency not found"
    spec = m.group(1)
    assert not spec.startswith("^"), "caret on 0.x pins httpx to a single minor"
    return SpecifierSet(spec)


def test_httpx_constraint_allows_modern_httpx():
    spec = _httpx_spec()
    assert "0.25.2" in spec
    assert "0.28.1" in spec
    assert "1.0.0" not in spec
