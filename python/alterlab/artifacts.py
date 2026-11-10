"""Retrieval helpers for private browser-download artifacts (#30596).

``download`` actions store the captured file privately and return
``artifact`` metadata on the action result. These helpers fetch that metadata,
mint a short-lived signed URL and save the bytes locally.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union
from urllib.parse import quote, urljoin, urlsplit

import httpx

from alterlab.actions import ArtifactMetadata


def _artifact_path(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError("artifact_id must be a non-empty string")
    return f"/api/v1/artifacts/{quote(artifact_id, safe='')}"


def _open_download_client() -> httpx.AsyncClient:
    """Client for the signed URL. Carries no API key: the URL authorises itself."""
    return httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60.0))


async def get_artifact(client: Any, artifact_id: str) -> ArtifactMetadata:
    """Return metadata of an artifact you own (``GET /api/v1/artifacts/{id}``)."""
    response = await client._request_with_retry("GET", _artifact_path(artifact_id))
    return ArtifactMetadata(response.json())


async def get_artifact_url(client: Any, artifact_id: str) -> Dict[str, Any]:
    """Mint a short-lived signed download URL (``GET /api/v1/artifacts/{id}/url``).

    A relative ``url`` (local storage backend) is resolved against the client's
    ``base_url`` so the returned value is always absolute.
    """
    response = await client._request_with_retry(
        "GET", _artifact_path(artifact_id) + "/url"
    )
    data: Dict[str, Any] = dict(response.json())
    url = data.get("url")
    if isinstance(url, str) and not urlsplit(url).scheme:
        data["url"] = urljoin(client.base_url + "/", url.lstrip("/"))
    return data


async def download_artifact(
    client: Any, artifact_id: str, path: Union[str, "os.PathLike[str]"]
) -> str:
    """Save an artifact to ``path`` and return the path written.

    The signed URL is fetched without the API key. Bytes are streamed to a
    temporary ``.part`` file and renamed on success, so a failed download never
    leaves a truncated file at ``path``.
    """
    info = await get_artifact_url(client, artifact_id)
    target = os.fspath(path)
    partial = target + ".part"
    try:
        async with _open_download_client() as http:
            async with http.stream("GET", info["url"]) as response:
                if response.status_code >= 400:
                    from alterlab.client import AlterLabAPIError

                    await response.aread()
                    raise AlterLabAPIError(
                        response.status_code, "artifact download failed", response
                    )
                with open(partial, "wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
        os.replace(partial, target)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return target
