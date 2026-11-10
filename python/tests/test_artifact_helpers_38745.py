"""#38745: artifact retrieval helpers and the 5-download client check."""

import httpx
import pytest

import alterlab
from alterlab import Actions, AlterLab, AlterLabAPIError, artifacts
from alterlab.actions import ActionResult, serialize_actions

META = {
    "artifact_id": "art_1",
    "filename": "f.pdf",
    "media_type": "application/pdf",
    "size_bytes": 3,
    "sha256": "abc",
    "status": "stored",
    "expires_at": 1.0,
}


def _client(handler):
    client = AlterLab(api_key="sk_test_dummy", base_url="https://api.example.test")
    client.client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
        headers={"X-API-Key": "sk_test_dummy"},
    )
    return client


def _url_payload(url):
    return {
        "artifact_id": "art_1",
        "url": url,
        "expires_in": 60,
        "filename": "f.pdf",
        "media_type": "application/pdf",
        "size_bytes": 3,
    }


def test_exports():
    for name in ("get_artifact", "get_artifact_url", "download_artifact", "artifacts"):
        assert name in alterlab.__all__


@pytest.mark.asyncio
async def test_get_artifact_returns_metadata():
    client = _client(lambda r: httpx.Response(200, json=META))
    meta = await client.get_artifact("art_1")
    assert meta.artifact_id == "art_1"
    assert meta["filename"] == "f.pdf"


@pytest.mark.asyncio
async def test_get_artifact_url_resolves_relative():
    rel = "/api/v1/artifacts/art_1/content?expires=9&signature=s"
    client = _client(lambda r: httpx.Response(200, json=_url_payload(rel)))
    info = await client.get_artifact_url("art_1")
    assert info["url"] == "https://api.example.test" + rel


@pytest.mark.asyncio
async def test_get_artifact_url_keeps_absolute():
    client = _client(
        lambda r: httpx.Response(
            200, json=_url_payload("https://r2.example.test/x?s=1")
        )
    )
    assert (await client.get_artifact_url("art_1"))[
        "url"
    ] == "https://r2.example.test/x?s=1"


@pytest.mark.asyncio
async def test_get_artifact_404_raises():
    client = _client(lambda r: httpx.Response(404, json={"detail": "gone"}))
    with pytest.raises(AlterLabAPIError):
        await client.get_artifact("art_1")


@pytest.mark.asyncio
async def test_download_writes_file_without_api_key(tmp_path, monkeypatch):
    seen = []

    def api(request):
        return httpx.Response(200, json=_url_payload("https://r2.example.test/x?s=1"))

    def storage(request):
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(200, content=b"abc")

    monkeypatch.setattr(
        artifacts,
        "_open_download_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(storage)),
    )
    out = tmp_path / "f.pdf"
    assert await _client(api).download_artifact("art_1", out) == str(out)
    assert out.read_bytes() == b"abc"
    assert not (tmp_path / "f.pdf.part").exists()
    assert seen == [None]


@pytest.mark.asyncio
async def test_download_failure_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        artifacts,
        "_open_download_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(403))
        ),
    )
    client = _client(
        lambda r: httpx.Response(200, json=_url_payload("https://r2.example.test/x"))
    )
    out = tmp_path / "f.pdf"
    with pytest.raises(AlterLabAPIError):
        await client.download_artifact("art_1", out)
    assert not out.exists()
    assert not (tmp_path / "f.pdf.part").exists()


def test_download_limit():
    one = Actions.download(url="https://x.io/f")
    assert len(serialize_actions([one] * 5)) == 5
    with pytest.raises(TypeError, match="at most 5"):
        serialize_actions([one] * 6)
    with pytest.raises(TypeError, match="at most 5"):
        serialize_actions([{"type": "download", "url": "https://x.io/f"}] * 6)


def test_action_result_without_artifact_unchanged():
    result = ActionResult({"index": 0, "type": "click", "success": True})
    assert result.artifact is None
    assert ActionResult({"artifact": META}).artifact.artifact_id == "art_1"
