"""``alterlab run`` create -> approve -> stream (resume) -> result against a fake runs API."""

import io
import json

import httpx
import pytest

from alterlab import cli, cli_runs
from alterlab.client import AlterLabError, AlterLabSync


class _Fake:
    def __init__(self):
        self.calls = []
        self.stream_attempts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, request.headers.get("Last-Event-ID")))
        assert request.headers["X-API-Key"] == "k"
        if request.method == "POST" and path == "/api/v1/runs":
            body = json.loads(request.content)
            assert body["max_credits"] == 500 and body["steps"]
            assert request.headers.get("Idempotency-Key") == "idem-1"
            return httpx.Response(
                201, json={"id": "run_1", "status": "awaiting_approval"}
            )
        if path == "/api/v1/runs/run_1/approve":
            return httpx.Response(200, json={"id": "run_1", "status": "running"})
        if path == "/api/v1/runs/run_1/events":
            self.stream_attempts += 1
            if request.headers.get("Last-Event-ID") is None:
                body = 'id: 1\nevent: run.started\ndata: {"seq":1,"type":"run.started"}\n\n'
                return httpx.Response(200, text=body)
            body = (
                'event: timeout\ndata: {"retry_ms": 1000}\n\n'
                'id: 2\nevent: run.succeeded\ndata: {"seq":2,"type":"run.succeeded"}\n\n'
            )
            return httpx.Response(200, text=body)
        if path == "/api/v1/runs/run_1":
            return httpx.Response(
                200, json={"id": "run_1", "status": "succeeded", "spent": 7}
            )
        if path == "/api/v1/runs/missing/approve":
            return httpx.Response(402, json={"detail": "Insufficient balance"})
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def run_env(monkeypatch):
    monkeypatch.setenv("ALTERLAB_API_KEY", "k")
    fake = _Fake()
    transport = httpx.MockTransport(fake.handler)
    real = cli_runs.cmd_run
    monkeypatch.setitem(
        cli.DATA_COMMANDS,
        "run",
        lambda args, client, stdin=None: real(
            args, client, stdin=stdin, transport=transport
        ),
    )
    return fake


def _run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, [json.loads(line) for line in out.out.splitlines() if line], out.err


def test_create_approve_stream_result_flow(run_env, capsys, tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"steps": [{"id": "s1", "type": "scrape", "params": {}}]})
    )
    code, out, _ = _run(
        [
            "run",
            "create",
            str(plan),
            "--max-credits",
            "500",
            "--idempotency-key",
            "idem-1",
        ],
        capsys,
    )
    assert code == 0 and out == [{"id": "run_1", "status": "awaiting_approval"}]
    code, out, _ = _run(["run", "approve", "run_1"], capsys)
    assert code == 0 and out[0]["status"] == "running"
    code, out, _ = _run(["run", "stream", "run_1"], capsys)
    assert code == 0 and [e["seq"] for e in out] == [1]
    code, out, _ = _run(["run", "stream", "run_1", "--last-event-id", "1"], capsys)
    assert [e["seq"] for e in out] == [2]  # resumed after seq 1, timeout frame skipped
    assert ("GET", "/api/v1/runs/run_1/events", "1") in run_env.calls
    code, out, _ = _run(["run", "result", "run_1"], capsys)
    assert out == [{"id": "run_1", "status": "succeeded", "spent": 7}]


def test_insufficient_balance_is_a_clean_error(run_env, capsys):
    code, out, err = _run(["run", "approve", "missing"], capsys)
    assert code == 1 and out == [] and "402" in err and "Insufficient balance" in err


def test_stream_reconnects_with_last_event_id(monkeypatch, capsys):
    monkeypatch.setenv("ALTERLAB_API_KEY", "k")
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadError("dropped")
        assert request.headers["Last-Event-ID"] == "5"
        return httpx.Response(200, text='id: 6\nevent: x\ndata: {"seq":6}\n\n')

    args = cli.build_parser().parse_args(
        ["run", "stream", "run_1", "--last-event-id", "5"]
    )
    client = AlterLabSync(api_key="k")
    assert cli_runs.cmd_run(args, client, transport=httpx.MockTransport(handler)) == 0
    assert json.loads(capsys.readouterr().out) == {"seq": 6}


def test_plan_from_stdin_and_bad_plan(run_env):
    assert cli_runs._load_plan("-", io.StringIO('{"steps": []}')) == {"steps": []}
    with pytest.raises(AlterLabError):
        cli_runs._load_plan("-", io.StringIO("[1]"))
