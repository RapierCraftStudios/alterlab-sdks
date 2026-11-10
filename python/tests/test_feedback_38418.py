"""#38418: client.feedback() and the `alterlab feedback` CLI."""

import json

import httpx
import pytest

from alterlab import AlterLab, AlterLabSync
from alterlab import cli


def _handler(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"report_id": "afb_1", "cluster_key": "ck1", "status": "received"}
        )

    return handler


def _patch(client, seen):
    client.client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(_handler(seen))
    )


@pytest.mark.asyncio
async def test_feedback_maps_fields_and_returns_status_url():
    seen = []
    client = AlterLab(api_key="sk_test_dummy")
    _patch(client, seen)
    result = await client.feedback(
        "blocked", "mode=auto", "empty body", expected="html", job_id="job_9"
    )
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/v1/agent/feedback"
    assert body == {
        "what_failed": "[blocked] empty body",
        "surface": "sdk",
        "what_tried": "mode=auto job_id=job_9",
        "what_expected": "html",
    }
    assert result["cluster_key"] == "ck1"
    assert result["status_url"] == "https://api.alterlab.io/api/v1/agent/feedback/ck1"


@pytest.mark.asyncio
async def test_feedback_truncates_and_omits_empty():
    seen = []
    client = AlterLab(api_key="sk_test_dummy")
    _patch(client, seen)
    await client.feedback("bug", None, "x" * 2000)
    body = json.loads(seen[0].content)
    assert len(body["what_failed"]) == 1000
    assert "what_tried" not in body and "what_expected" not in body


def test_sync_feedback_and_cli(monkeypatch, capsys):
    seen = []
    real_init = AlterLabSync.__init__

    def init(self, *a, **k):
        real_init(self, *a, **k)
        _patch(self._client, seen)

    monkeypatch.setattr(AlterLabSync, "__init__", init)
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("ALTERLAB_LAST_JOB_ID", "job_env")
    assert cli.main(["feedback", "--category", "docs", "--message", "unclear"]) == 0
    out = capsys.readouterr().out
    assert "cluster_key: ck1" in out and "status_url: " in out
    assert "job_id=job_env" in json.loads(seen[0].content)["what_tried"]
    assert (
        cli.main(["feedback", "--category", "docs", "--message", "m", "--job-id", "j2"])
        == 0
    )
    assert "job_id=j2" in json.loads(seen[1].content)["what_tried"]
