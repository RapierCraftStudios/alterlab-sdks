"""Tests for AlterLabFallbackTool: AlterLab is used only on a block signal."""

from typing import Any, List, Type

import pytest
from crewai.tools import BaseTool
from pydantic import BaseModel

from crewai_alterlab.fallback import AlterLabFallbackTool, is_blocked

GOOD_PAGE = (
    "<html><body><h1>Article</h1>"
    + "<p>Real content sentence.</p>" * 10
    + "</body></html>"
)
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
JS_SHELL = (
    '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
)


class _Input(BaseModel):
    url: str


class RecordingTool(BaseTool):
    name: str = "recording"
    description: str = "records calls"
    args_schema: Type[BaseModel] = _Input
    calls: List[str] = []

    def _run(self, url: str) -> str:
        self.calls.append(url)
        return "alterlab:" + url


def _tool(result: Any):
    fallback = RecordingTool(calls=[])
    fetched: List[str] = []

    def fetch(url: str) -> Any:
        fetched.append(url)
        if isinstance(result, Exception):
            raise result
        return result

    return AlterLabFallbackTool(fetch=fetch, fallback=fallback), fallback, fetched


@pytest.mark.parametrize(
    "result",
    [
        (403, "Forbidden"),
        (429, "slow down"),
        (200, CHALLENGE),
        (200, JS_SHELL),
        (200, ""),
    ],
)
def test_block_signals_retry_via_alterlab(result):
    tool, fallback, fetched = _tool(result)
    assert tool.run(url="https://example.com/p") == "alterlab:https://example.com/p"
    assert fetched == ["https://example.com/p"]
    assert fallback.calls == ["https://example.com/p"]


@pytest.mark.parametrize(
    "result", [(200, GOOD_PAGE), (404, "Not found"), (500, "boom"), GOOD_PAGE]
)
def test_non_block_results_never_call_alterlab(result):
    tool, fallback, _ = _tool(result)
    out = tool.run(url="https://example.com/p")
    assert out == (result[1] if isinstance(result, tuple) else result)
    assert fallback.calls == []


def test_response_object_is_accepted():
    class Resp:
        status_code = 403
        text = "denied"

    tool, fallback, _ = _tool(Resp())
    assert tool.run(url="https://example.com/p").startswith("alterlab:")
    assert fallback.calls == ["https://example.com/p"]


def test_network_error_is_not_a_block_signal():
    tool, fallback, _ = _tool(ConnectionError("dns"))
    with pytest.raises(ConnectionError):
        tool.run(url="https://example.com/p")
    assert fallback.calls == []


def test_is_blocked_ignores_plain_text_pages():
    assert not is_blocked(200, "Plain text body that is a normal document.")
    assert not is_blocked(None, GOOD_PAGE)
