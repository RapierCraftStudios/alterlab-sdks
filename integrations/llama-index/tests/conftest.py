"""Test shim: the reader imports ``alterlab`` lazily inside ``__init__``, so the
``llama_index.readers.alterlab.base.AlterLabSync``/``AdvancedOptions`` names the
tests patch do not exist at module level. Expose them on the module and route the
lazy ``from alterlab import ...`` through them, so ``patch`` takes effect.
"""

import alterlab
import pytest

import llama_index.readers.alterlab.base as _base


@pytest.fixture(autouse=True)
def _route_alterlab_names(monkeypatch):
    real_sync, real_opts = alterlab.AlterLabSync, alterlab.AdvancedOptions
    monkeypatch.setattr(_base, "AlterLabSync", real_sync, raising=False)
    monkeypatch.setattr(_base, "AdvancedOptions", real_opts, raising=False)
    monkeypatch.setattr(
        alterlab, "AlterLabSync", lambda *a, **k: _base.AlterLabSync(*a, **k)
    )
    monkeypatch.setattr(
        alterlab, "AdvancedOptions", lambda *a, **k: _base.AdvancedOptions(*a, **k)
    )
    yield
