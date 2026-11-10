"""#39854: `alterlab hands delegate` drives the delegated run routes."""

import json

import pytest

from alterlab import cli, cli_hands
from alterlab.client import AlterLabError

RUN = "77777777-2222-3333-4444-555555555555"


class _Client:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def hands_request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.reply


def _run(reply, *argv):
    args = cli.build_parser().parse_args(["hands", "delegate", *argv])
    client = _Client(reply)
    return cli_hands.run(args, client), client


def test_create_posts_goal_target_and_preview_mode(capsys):
    code, client = _run(
        {"id": RUN, "state": "planned"},
        "create",
        "--goal",
        "update my address",
        "--target-url",
        "https://portal.test/x",
        "--policy",
        "checkout",
        "--preview",
    )
    assert code == 0
    assert client.calls == [
        (
            "POST",
            "/runs",
            {
                "goal": "update my address",
                "mode": "preview",
                "target": {"type": "url", "value": "https://portal.test/x"},
                "policy_ref": "checkout",
            },
        )
    ]
    assert RUN in capsys.readouterr().out


def test_events_prints_one_event_per_line_after_the_cursor(capsys):
    events = [
        {"seq": 4, "stage": "finding", "kind": "fact"},
        {"seq": 5, "stage": "x", "kind": "y"},
    ]
    code, client = _run(events, "events", RUN, "--after", "3")
    assert code == 0
    assert client.calls == [("GET", f"/runs/{RUN}/events?after=3", None)]
    assert len(capsys.readouterr().out.strip().splitlines()) == 2


def test_advance_sends_facts_act_and_finish():
    facts = [{"subject": "user", "key": "user.address.home", "value": "x"}]
    act = {"actions": [{"type": "click", "selector": "#go"}]}
    _, client = _run(
        {},
        "advance",
        RUN,
        "--facts",
        json.dumps(facts),
        "--act",
        json.dumps(act),
        "--finish",
    )
    assert client.calls == [
        ("POST", f"/runs/{RUN}/advance", {"facts": facts, "finish": True, "act": act})
    ]


def test_answer_posts_the_decision_and_requires_one():
    _, client = _run({}, "answer", RUN, "--request", "r1", "--approve")
    assert client.calls == [
        (
            "POST",
            f"/runs/{RUN}/answer",
            {"request_id": "r1", "decision": "approve", "answer": None},
        )
    ]
    with pytest.raises(AlterLabError):
        _run({}, "answer", RUN, "--request", "r1")


def test_missing_run_id_and_goal_are_refused():
    with pytest.raises(AlterLabError):
        _run({}, "status")
    with pytest.raises(AlterLabError):
        _run({}, "create")
