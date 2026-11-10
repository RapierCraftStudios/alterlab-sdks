"""Test shims for the crewai version an unpinned resolve can install.

``alterlab`` pins ``httpx<0.26``, which excludes every crewai>=1.0, so the
resolver lands on crewai 0.80 / chromadb 0.5. Those import-time paths use APIs
newer environments no longer ship: NumPy 2.0 removed ``np.float_``, and current
setuptools no longer provides ``pkg_resources``. Restore minimal equivalents
before ``crewai`` is imported so the tool tests can collect.
"""

import importlib.metadata
import sys
import types

import numpy as np

for _alias, _target in (("float_", "float64"), ("complex_", "complex128")):
    if not hasattr(np, _alias):
        setattr(np, _alias, getattr(np, _target))

try:
    import pkg_resources  # noqa: F401
except ImportError:
    _pkg_resources = types.ModuleType("pkg_resources")
    _pkg_resources.DistributionNotFound = importlib.metadata.PackageNotFoundError
    _pkg_resources.get_distribution = lambda name: types.SimpleNamespace(
        version=importlib.metadata.version(name)
    )
    sys.modules["pkg_resources"] = _pkg_resources
