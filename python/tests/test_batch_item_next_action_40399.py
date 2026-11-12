"""Coverage for #40399: the generated BatchItemStatus type carries the per-item
``next_action`` added by #40359.

Parsed with ``ast`` so the check needs no SDK runtime dependencies.
"""

import ast
from pathlib import Path

TRANSPORT = Path(__file__).resolve().parents[1] / "alterlab" / "_transport.py"


def test_batch_item_status_declares_next_action():
    tree = ast.parse(TRANSPORT.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BatchItemStatus")
    fields = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)}
    assert "next_action" in fields
