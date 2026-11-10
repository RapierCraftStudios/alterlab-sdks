"""``alterlab hands`` commands (#39556)."""

import json

import pytest

from alterlab import cli, cli_data, cli_hands


class FakeClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def hands_request(self, method, path, body=None):
        self.calls.append((method, path, body))
        value = self.responses.get((method, path), {})
        return value.pop(0) if isinstance(value, list) else value


@pytest.fixture
def fake(monkeypatch):
    c = FakeClient()
    monkeypatch.setattr(cli_data, "client_from_env", lambda: c)
    monkeypatch.setattr(cli_hands, "POLL_S", 0)
    return c


def out_lines(capsys):
    return [json.loads(x) for x in capsys.readouterr().out.splitlines()]


def test_connect_polls_until_connected(fake, capsys):
    fake.responses = {
        ("POST", "/connect"): {"connect_id": "c1", "link": "https://x/c1"},
        ("GET", "/connect/c1"): [
            {"status": "pending"},
            {"status": "connected", "session": "s1"},
        ],
    }
    assert cli.main(["hands", "connect", "reddit.com", "--scope", "hands:read"]) == 0
    assert fake.calls[0] == (
        "POST",
        "/connect",
        {"site": "reddit.com", "reason": "", "scopes": ["hands:read"]},
    )
    assert out_lines(capsys)[-1]["session"] == "s1"


def test_connect_no_wait_does_not_poll(fake, capsys):
    fake.responses = {("POST", "/connect"): {"connect_id": "c1", "link": "l"}}
    assert cli.main(["hands", "connect", "reddit.com", "--no-wait"]) == 0
    assert len(fake.calls) == 1


def test_connect_expired_fails(fake, capsys):
    fake.responses = {
        ("POST", "/connect"): {"connect_id": "c1"},
        ("GET", "/connect/c1"): {"status": "expired"},
    }
    assert cli.main(["hands", "connect", "reddit.com"]) == 1


def test_sessions_list_and_revoke(fake, capsys):
    fake.responses = {
        ("GET", "/sessions"): {"sessions": [{"session": "s1"}, {"session": "s2"}]},
        ("DELETE", "/sessions/s1"): {"session": "s1", "revoked": True},
    }
    assert cli.main(["hands", "sessions"]) == 0
    assert [x["session"] for x in out_lines(capsys)] == ["s1", "s2"]
    assert cli.main(["hands", "sessions", "--revoke", "s1"]) == 0
    assert out_lines(capsys)[0]["revoked"] is True


def test_run_builds_task_from_params(fake, capsys):
    fake.responses = {("POST", "/tasks"): {"id": "t1"}}
    rc = cli.main(
        [
            "hands",
            "run",
            "reddit-saved",
            "--param",
            "site=reddit.com",
            "--param",
            "limit=5",
            "--session",
            "s1",
        ]
    )
    assert rc == 0
    _, _, body = fake.calls[0]
    assert body["start_url"] == "https://reddit.com"
    assert body["session_id"] == "s1" and body["mode"] == "read"
    assert "reddit-saved" in body["instruction"] and "limit=5" in body["instruction"]


def test_run_rejects_bad_param_and_missing_url(fake, capsys):
    assert cli.main(["hands", "run", "r", "--param", "oops"]) == 1
    assert cli.main(["hands", "run", "r"]) == 1
    assert fake.calls == []


def test_answer_bodies(fake, capsys):
    fake.responses = {("POST", "/tasks/t1/answer"): {"status": "answered"}}
    assert cli.main(["hands", "answer", "t1", "--request", "r1", "--approve"]) == 0
    assert fake.calls[-1][2] == {
        "request_id": "r1",
        "decision": "approve",
        "answer": None,
    }
    assert (
        cli.main(["hands", "answer", "t1", "--request", "r1", "--answer", "yes"]) == 0
    )
    assert fake.calls[-1][2]["answer"] == "yes"
    assert cli.main(["hands", "answer", "t1", "--request", "r1", "--deny"]) == 0
    assert fake.calls[-1][2]["decision"] == "deny"


def test_answer_validation_and_pending(fake, capsys):
    assert cli.main(["hands", "answer", "t1", "--request", "r1"]) == 1
    assert (
        cli.main(["hands", "answer", "t1", "--request", "r1", "--approve", "--deny"])
        == 1
    )
    fake.responses = {("GET", "/requests/pending"): [[{"id": "r1"}]]}
    assert cli.main(["hands", "answer", "--pending"]) == 0
    assert out_lines(capsys) == [{"id": "r1"}]


def test_facts_put_sends_json_value_and_get_lists(fake, capsys):
    fake.responses = {
        ("PUT", "/facts"): {"key": "user.address.home", "status": "unconfirmed"},
        ("GET", "/facts?subject=user&prefix=user."): {
            "facts": [{"key": "user.address.home"}]
        },
    }
    argv = ["hands", "facts", "put", "--subject", "user", "--key", "user.address.home"]
    assert (
        cli.main(
            argv + ["--value", '{"city": "Oslo"}', "--kind", "address", "--ttl", "60"]
        )
        == 0
    )
    assert fake.calls[0] == (
        "PUT",
        "/facts",
        {
            "subject": "user",
            "key": "user.address.home",
            "value": {"city": "Oslo"},
            "kind": "address",
            "ttl_s": 60,
        },
    )
    assert (
        cli.main(["hands", "facts", "get", "--subject", "user", "--prefix", "user."])
        == 0
    )
    assert fake.calls[1][:2] == ("GET", "/facts?subject=user&prefix=user.")
    assert out_lines(capsys)[-1]["key"] == "user.address.home"


def test_facts_confirm_and_history_require_subject_and_key(fake):
    fake.responses = {("POST", "/facts/confirm"): {"status": "confirmed"}}
    assert (
        cli.main(["hands", "facts", "confirm", "--subject", "user", "--key", "k"]) == 0
    )
    assert fake.calls[0] == ("POST", "/facts/confirm", {"subject": "user", "key": "k"})
    assert cli.main(["hands", "facts", "history", "--subject", "user"]) != 0
    assert len(fake.calls) == 1
