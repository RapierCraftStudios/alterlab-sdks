"""``alterlab hands schema`` (#39813)."""

import json

import pytest

from alterlab import cli, cli_data
from test_cli_hands_39556 import FakeClient, out_lines  # noqa: F401


@pytest.fixture
def fake(monkeypatch):
    c = FakeClient()
    monkeypatch.setattr(cli_data, "client_from_env", lambda: c)
    return c


def test_schema_posts_to_the_task_and_prints_json(fake, capsys):
    fake.responses = {
        ("POST", "/tasks/t1/schema"): {"page_schema": {"schema_hash": "sha256:a", "fields": []}}
    }
    assert cli.main(["hands", "schema", "t1"]) == 0
    assert fake.calls == [("POST", "/tasks/t1/schema", None)]
    assert out_lines(capsys)[0]["page_schema"]["schema_hash"] == "sha256:a"


def test_schema_requires_a_task_id(fake):
    with pytest.raises(SystemExit):
        cli.main(["hands", "schema"])
