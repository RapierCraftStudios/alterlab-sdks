"""Fetch directly first; call AlterLab only after the direct fetch was blocked.

With ``ALTERLAB_API_KEY`` the fallback uses that key. Without one it mints a keyless trial
key (``POST /api/v1/agent/trial``), which the server caps per IP per day and by a global
daily budget. Past a cap, or on any fallback failure, the original blocked response is
returned with ``get_key_url`` and ``next_action`` instead. The wrapper never raises because
of the fallback and never retries it.
"""

import os
import time
from typing import Any, Dict, Optional

import httpx

from unblock_fetch.detector import detect_block

SOURCE = "unblock-fetch"
DEFAULT_BASE_URL = "https://api.alterlab.io"
DEFAULT_GET_KEY_URL = (
    "https://alterlab.io/signup?source=unblock-fetch&utm_source=unblock-fetch"
    "&utm_medium=sdk&utm_campaign=keyless-fallback"
)
_ATTRIBUTION = {
    "source": SOURCE,
    "utm_source": SOURCE,
    "utm_medium": "sdk",
    "utm_campaign": "keyless-fallback",
}
_NEXT_ACTION = (
    "Get a free key at get_key_url and set ALTERLAB_API_KEY to keep unblocking."
)

# Trial keys minted by this process, per base URL, so one process mints at most one.
_trial_keys: Dict[str, str] = {}


def _version() -> str:
    from unblock_fetch import __version__

    return __version__


class FetchResult:
    """Response shape of ``requests``/``httpx`` plus ``via`` (``direct`` | ``alterlab``)."""

    def __init__(
        self,
        status_code: int,
        text: str,
        headers: Optional[Dict[str, str]] = None,
        url: str = "",
        via: str = "direct",
        content: Optional[bytes] = None,
        **extra: Any,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers or {}
        self.url = url
        self.via = via
        self.attribution: Optional[Dict[str, str]] = extra.get("attribution")
        self.get_key_url: Optional[str] = extra.get("get_key_url")
        self.next_action: Optional[str] = extra.get("next_action")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        import json

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} for {self.url}",
                request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code, text=self.text),
            )


def _direct(resp: httpx.Response, url: str, **extra: Any) -> FetchResult:
    return FetchResult(
        resp.status_code, resp.text, dict(resp.headers), str(resp.url or url), "direct",
        content=resp.content, **extra,
    )  # fmt: skip


def _page_text(result: Dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, dict):
        for fmt in ("markdown", "text", "html"):
            if content.get(fmt):
                return content[fmt]
        return ""
    return content if isinstance(content, str) else ""


def _scrape(
    client: httpx.Client, base: str, key: str, url: str, timeout: float
) -> Optional[dict]:
    headers = {"X-API-Key": key, "X-AlterLab-Source": f"{SOURCE}/{_version()}"}
    resp = client.post(
        f"{base}/api/v1/scrape",
        json={"url": url, "sync": True},
        headers=headers,
        timeout=timeout + 30,
    )
    if resp.status_code == 202 and "job_id" in resp.json():
        job_id = resp.json()["job_id"]
        deadline = time.monotonic() + timeout + 30
        while time.monotonic() < deadline:
            resp = client.get(
                f"{base}/api/v1/jobs/{job_id}", params={"wait": 10}, headers=headers,
                timeout=30,
            )  # fmt: skip
            if resp.status_code == 200 and resp.json().get("status") not in (
                "pending", "queued", "running", "processing",
            ):  # fmt: skip
                break
    if resp.status_code != 200:
        return None
    return resp.json()


def _keyless_key(
    client: httpx.Client, base: str
) -> "tuple[Optional[str], Dict[str, Any]]":
    """Return ``(trial_key, hint)``; ``hint`` carries the server's get_key_url when capped."""
    if base in _trial_keys:
        return _trial_keys[base], {}
    resp = client.post(
        f"{base}/api/v1/agent/trial",
        headers={"X-AlterLab-Source": f"{SOURCE}/{_version()}"},
        timeout=15,
    )
    body = (
        resp.json()
        if resp.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if resp.status_code == 201 and body.get("key"):
        _trial_keys[base] = body["key"]
        return body["key"], body
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
    return None, detail


def fetch_with_fallback(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 20.0,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> FetchResult:
    """Drop-in for ``requests.get``/``httpx.get`` (url, headers, timeout)."""
    own = client is None
    http = client or httpx.Client(follow_redirects=True)
    try:
        direct = http.get(url, headers=headers, timeout=timeout)
        if not detect_block(direct.status_code, direct.text):
            return _direct(direct, url)
        base = (
            base_url or os.environ.get("ALTERLAB_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        key = api_key or os.environ.get("ALTERLAB_API_KEY")
        hint: Dict[str, Any] = {}
        try:
            if not key:
                key, hint = _keyless_key(http, base)
            result = _scrape(http, base, key, url, timeout) if key else None
        except (httpx.HTTPError, ValueError):
            result = None
        if result is None:
            return _direct(
                direct, url,
                get_key_url=hint.get("get_key_url") or DEFAULT_GET_KEY_URL,
                next_action=_NEXT_ACTION,
            )  # fmt: skip
        keyless = not (api_key or os.environ.get("ALTERLAB_API_KEY"))
        return FetchResult(
            int(result.get("status_code") or 200), _page_text(result), {}, url, "alterlab",
            attribution=dict(_ATTRIBUTION),
            get_key_url=DEFAULT_GET_KEY_URL,
            next_action=_NEXT_ACTION if keyless else None,
        )  # fmt: skip
    finally:
        if own:
            http.close()
