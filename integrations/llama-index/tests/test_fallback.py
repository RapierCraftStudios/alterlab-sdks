"""Tests for FetchFallbackAdapter: AlterLab is used only on a block signal."""

from typing import Any, List

import pytest

from llama_index.readers.alterlab.fallback import (
    FetchFallbackAdapter,
    is_blocked,
)

GOOD_PAGE = (
    "<html><body><h1>Article</h1>"
    + "<p>Real content sentence.</p>" * 10
    + "</body></html>"
)
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
JS_SHELL = (
    '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
)


class RecordingScraper:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def scrape(self, url: str) -> str:
        self.calls.append(url)
        return "alterlab:" + url


def _tool(result: Any):
    scraper = RecordingScraper()
    fetched: List[str] = []

    def fetch(url: str) -> Any:
        fetched.append(url)
        if isinstance(result, Exception):
            raise result
        return result

    return FetchFallbackAdapter(fetch=fetch, fallback=scraper), scraper, fetched


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
    tool, scraper, fetched = _tool(result)
    assert tool.fetch("https://example.com/p") == "alterlab:https://example.com/p"
    assert fetched == ["https://example.com/p"]
    assert scraper.calls == ["https://example.com/p"]


@pytest.mark.parametrize(
    "result", [(200, GOOD_PAGE), (404, "Not found"), (500, "boom"), GOOD_PAGE]
)
def test_non_block_results_never_call_alterlab(result):
    tool, scraper, _ = _tool(result)
    out = tool.fetch("https://example.com/p")
    assert out == (result[1] if isinstance(result, tuple) else result)
    assert scraper.calls == []


def test_response_object_is_accepted():
    class Resp:
        status_code = 403
        text = "denied"

    tool, scraper, _ = _tool(Resp())
    assert tool.fetch("https://example.com/p").startswith("alterlab:")
    assert scraper.calls == ["https://example.com/p"]


def test_network_error_is_not_a_block_signal():
    tool, scraper, _ = _tool(ConnectionError("dns"))
    with pytest.raises(ConnectionError):
        tool.fetch("https://example.com/p")
    assert scraper.calls == []


def test_is_blocked_ignores_plain_text_pages():
    assert not is_blocked(200, "Plain text body that is a normal document.")
    assert not is_blocked(None, GOOD_PAGE)


def test_to_tool_wraps_fetch():
    pytest.importorskip("llama_index.core.tools")
    tool, scraper, _ = _tool((403, "Forbidden"))
    out = tool.to_tool().call(url="https://example.com/p")
    assert "alterlab:https://example.com/p" in str(out)
