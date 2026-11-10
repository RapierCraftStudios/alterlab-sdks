"""Run `async def` tests with asyncio.run when pytest-asyncio is not installed.

`pytest.mark.asyncio` tests otherwise fail under a bare `uv run --with pytest`.
"""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

# `poetry install --no-root` does not put the package on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run the coroutine test in an event loop")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.config.pluginmanager.has_plugin("asyncio"):
        return None
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    args = {a: pyfuncitem.funcargs[a] for a in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(pyfuncitem.obj(**args))
    return True
