"""#38951: the alterlab CLI (login, data commands, local tools, stdio MCP)."""

import io
import json
from pathlib import Path

import httpx
import pytest

from alterlab import cli, cli_auth, cli_data, cli_local, mcp_stdio


def _http(handler):
    return httpx.Client(
        base_url="https://api.alterlab.io", transport=httpx.MockTransport(handler)
    )


def test_login_stores_key_and_never_prints_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
    monkeypatch.setattr(cli_auth, "_keyring", lambda: None)
    polls = []

    def handler(request):
        if request.method == "POST":
            assert request.url.path == "/api/v1/agent/signup"
            return httpx.Response(
                201,
                json={
                    "signup_id": "s1",
                    "verification_url": "https://x/v",
                    "user_code": "ABCD",
                    "poll_interval": 1,
                    "expires_in": 60,
                },
            )
        polls.append(1)
        if len(polls) == 1:
            return httpx.Response(200, json={"status": "pending", "poll_interval": 1})
        return httpx.Response(
            200,
            json={
                "status": "approved",
                "api_key": "sk_live_SECRET",
                "key_prefix": "sk_live_SE",
                "poll_interval": 1,
            },
        )

    rc = cli_auth.login("a@b.co", client=_http(handler), sleep=lambda s: None)
    out = capsys.readouterr()
    assert rc == 0
    assert "sk_live_SECRET" not in out.out + out.err
    assert "ABCD" in out.err
    assert cli_auth.load_key() == "sk_live_SECRET"
    assert (
        oct((tmp_path / "alterlab" / "credentials.json").stat().st_mode & 0o777)
        == "0o600"
    )


def test_login_already_delivered_key_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "signup_id": "s1",
                    "verification_url": "u",
                    "user_code": "C",
                    "poll_interval": 1,
                    "expires_in": 60,
                },
            )
        return httpx.Response(
            200, json={"status": "approved", "key_delivered": True, "poll_interval": 1}
        )

    assert cli_auth.login("a@b.co", client=_http(handler), sleep=lambda s: None) == 1
    assert "already delivered" in capsys.readouterr().err


class FakeClient:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def estimate_cost(self, url, **kw):
        self.calls.append(("estimate", url))
        return {"estimated_cost_usd": 0.01, "estimated_cost_microcents": 10000}

    def scrape(self, url, **kw):
        self.calls.append(("scrape", url))
        return {"content": "# hi", "billing": {"final_cost_microcents": 5000}}

    def map(self, url, **kw):
        return {
            "urls": ["https://e.com/a", "https://e.com/b"],
            "estimated_cost_usd": 0.0,
        }

    def search(self, q, **kw):
        return {"results": [{"title": "t"}], "credits_used": 1}

    def crawl_and_wait(self, url, **kw):
        return {"pages": [{"url": url}, {"url": url + "/2"}]}


@pytest.fixture
def fake(monkeypatch):
    c = FakeClient()
    monkeypatch.setattr(cli_data, "client_from_env", lambda: c)
    return c


def test_scrape_markdown_with_cost_on_stderr(fake, capsys):
    assert cli.main(["scrape", "https://e.com"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "# hi"
    assert "cost $0.0050" in out.err


def test_map_streams_ndjson(fake, capsys):
    assert cli.main(["map", "https://e.com"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(x)["url"] for x in lines] == [
        "https://e.com/a",
        "https://e.com/b",
    ]


def test_crawl_and_search_stream_ndjson(fake, capsys):
    assert cli.main(["crawl", "https://e.com", "--max", "2"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 2
    assert cli.main(["search", "q", "--content"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "t"


def test_estimate_prints_quote_and_does_not_scrape(fake, capsys):
    assert cli.main(["scrape", "https://e.com", "--estimate"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["estimated_cost_usd"] == 0.01
    assert "estimated $0.0100" in out.err
    assert ("scrape", "https://e.com") not in fake.calls


def test_max_cost_blocks_expensive_scrape(fake, capsys):
    assert cli.main(["scrape", "https://e.com", "--max-cost", "0.001"]) == 1
    assert "exceeds --max-cost" in capsys.readouterr().err
    assert not any(c[0] == "scrape" for c in fake.calls)
    assert cli.main(["scrape", "https://e.com", "--max-cost", "0.5"]) == 0


def test_max_cost_fails_closed_without_estimator(fake, capsys):
    assert cli.main(["search", "q", "--max-cost", "1"]) == 1
    assert "cannot enforce" in capsys.readouterr().err


def test_batch_reads_stdin(fake, monkeypatch, capsys):
    fake.batch_scrape = lambda reqs: {"jobs": [{"url": r["url"]} for r in reqs]}
    monkeypatch.setattr("sys.stdin", io.StringIO("https://a.co\nhttps://b.co\n"))
    assert cli.main(["batch"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 2


def test_fetch_skips_alterlab_when_direct_works(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_data.httpx,
        "get",
        lambda *a, **k: httpx.Response(200, text="<h1>Hi</h1>" + "x" * 10),
    )
    monkeypatch.setattr(
        cli_data, "client_from_env", lambda: pytest.fail("must not call AlterLab")
    )
    assert cli.main(["fetch", "https://e.com"]) == 0
    assert "# Hi" in capsys.readouterr().out


def test_fetch_falls_back_when_blocked(fake, monkeypatch, capsys):
    monkeypatch.setattr(
        cli_data.httpx, "get", lambda *a, **k: httpx.Response(403, text="no")
    )
    assert cli.main(["fetch", "https://e.com"]) == 0
    assert ("scrape", "https://e.com") in fake.calls


@pytest.fixture
def no_alterlab_network(monkeypatch):
    """Local tools may hit the target only; any AlterLab host or client use fails."""
    seen = []
    real = httpx.Client.send

    def send(self, request, **kw):
        seen.append(str(request.url))
        assert "alterlab" not in request.url.host
        return httpx.Response(
            200,
            headers={"server": "cloudflare", "cf-ray": "1"},
            text="User-agent: GPTBot\nDisallow: /\nSitemap: https://e.com/s.xml\n",
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(
        cli_data,
        "client_from_env",
        lambda: pytest.fail("local tool used an AlterLab client"),
    )
    monkeypatch.setattr(cli_local, "_tls_info", lambda url: {})
    return seen


def test_local_tools_make_no_alterlab_calls(no_alterlab_network, tmp_path, capsys):
    page = tmp_path / "p.html"
    page.write_text("<h1>T</h1><p>a <a href='/x'>l</a></p>")
    for argv in (
        ["detect", "https://e.com"],
        ["doctor", "https://e.com"],
        ["robots", "https://e.com"],
        ["md", str(page)],
    ):
        assert cli.main(argv) == 0
    assert no_alterlab_network and all("e.com" in u for u in no_alterlab_network)
    out = capsys.readouterr().out
    assert "# T" in out and "[l](/x)" in out


def test_detect_and_robots_results(no_alterlab_network, capsys):
    cli.main(["detect", "https://e.com"])
    assert "cloudflare" in capsys.readouterr().out
    result = cli_local.robots("https://e.com/path")
    assert result["ai_crawlers"]["GPTBot"] == "blocked"
    assert result["ai_crawlers"]["CCBot"] == "allowed"
    assert result["sitemaps"] == ["https://e.com/s.xml"]


def test_mcp_lists_full_bundled_tool_list():
    tools = mcp_stdio.load_tool_definitions()
    reply = mcp_stdio.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [t["name"] for t in reply["result"]["tools"]] == [t["name"] for t in tools]
    assert len(tools) >= 10
    shared = (
        Path(__file__).resolve().parents[3] / "shared/mcp_tools/tool_definitions.json"
    )
    if shared.exists():
        assert json.loads(shared.read_text())["tools"] == tools


def test_mcp_call_and_serve_roundtrip():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "alterlab_scrape",
                "arguments": {"url": "https://e.com"},
            },
        },
    ]
    out = io.StringIO()
    mcp_stdio.serve(io.StringIO("\n".join(json.dumps(m) for m in msgs)), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert (
        len(replies) == 2 and replies[0]["result"]["serverInfo"]["name"] == "alterlab"
    )
    assert (
        replies[1]["result"]["isError"] is True
    )  # not logged in, surfaced as tool error


def test_skill_install(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTERLAB_SKILLS_DIR", str(tmp_path))
    assert cli.main(["skill", "install"]) == 0
    assert "alterlab scrape" in (tmp_path / "alterlab" / "SKILL.md").read_text()


def test_unauthenticated_data_command_errors_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
    monkeypatch.setattr(cli_auth, "_keyring", lambda: None)
    assert cli.main(["map", "https://e.com"]) == 1
    assert "alterlab login" in capsys.readouterr().err
