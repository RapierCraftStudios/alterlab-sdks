"""Drop-in ``requests``-compatible wrapper around the AlterLab SDK.

Lets agents swap a single import line and keep writing otherwise-standard
``requests``-style code, while every call is routed through AlterLab's
challenge-handling scraping pipeline instead of a bare socket connection.

Example::

    from alterlab import requests

    # Reads ALTERLAB_API_KEY from the environment on first call.
    response = requests.get("https://example.com", headers={"X-Custom": "1"})
    print(response.status_code)
    print(response.text)
    data = requests.post("https://api.example.com/thing", json={"a": 1}).json()

Configure explicitly instead of (or in addition to) the environment variable::

    from alterlab import requests

    requests.configure(api_key="sk_live_...")
    response = requests.get("https://example.com")

Internally every call goes through :class:`alterlab.client.AlterLabSync`,
which itself calls the existing ``/api/v1/scrape`` endpoint — no new backend
endpoint is introduced by this module.

Deviation from the real ``requests`` library: AlterLab-specific errors
(:class:`alterlab.client.AlterLabAPIError` and its subclasses, e.g.
:class:`~alterlab.client.AuthenticationError`,
:class:`~alterlab.client.InsufficientFundsError`,
:class:`~alterlab.client.RateLimitError`) propagate directly rather than
being wrapped in ``requests.exceptions`` types. Catch
``alterlab.AlterLabAPIError`` (or a specific subclass) instead of
``requests.exceptions.HTTPError``. This also applies to
:meth:`Response.raise_for_status`: it raises :class:`AlterLabHTTPError` (a
subclass of ``AlterLabAPIError``) for a 4xx/5xx status returned by the
*target site* through an otherwise-successful scrape — not
``requests.exceptions.HTTPError`` and not a bare ``RuntimeError``.
"""

import json as _json
import os
from typing import Any, Dict, Optional, Union
from urllib.parse import urlencode, urlsplit, urlunsplit

from alterlab.client import AlterLabAPIError, AlterLabSync, AlterLabValidationError

__all__ = [
    "Response",
    "AlterLabHTTPError",
    "configure",
    "request",
    "get",
    "post",
    "put",
    "patch",
    "delete",
]


class AlterLabHTTPError(AlterLabAPIError):
    """Raised by :meth:`Response.raise_for_status` for a 4xx/5xx status code
    returned by the *target site* through an otherwise-successful scrape.

    This is a subclass of :class:`alterlab.client.AlterLabAPIError`, so
    existing ``except AlterLabAPIError`` (or ``except alterlab.AlterLabError``)
    handlers catch it too, consistent with the rest of the SDK's exception
    hierarchy. Distinct from the exceptions raised during the request itself
    (e.g. :class:`~alterlab.client.AuthenticationError`,
    :class:`~alterlab.client.RateLimitError`) — this one reflects the
    scraped page's own HTTP status, not a failure of the AlterLab API call.

    Example::

        try:
            response = requests.get("https://example.com/missing")
            response.raise_for_status()
        except AlterLabHTTPError as e:
            print(f"Target site returned {e.status_code}")
    """

    pass


_ENV_API_KEY = "ALTERLAB_API_KEY"

# Mirrors the Literal values of AlterLabSync.scrape()'s `content_type` parameter
# (client.py) and the server-side allowlist enforced in
# services/api/app/routers/scrape_unified.py (`_ALLOWED_CONTENT_TYPES`). Keep
# these three lists in sync if the API ever adds a supported content type.
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/x-www-form-urlencoded",
        "text/plain",
        "application/graphql",
    }
)

# Lazily-initialized module-level singleton — importing this module must not
# require ALTERLAB_API_KEY to be set. Configured either via configure()
# (explicit) or lazily from the environment on first request.
_client: Optional[AlterLabSync] = None
_configured_api_key: Optional[str] = None


class Response:
    """A ``requests.Response``-compatible view over an AlterLab scrape result.

    Backed by the scrape response dict returned by
    :meth:`alterlab.client.AlterLabSync.scrape`. Exposes the small subset of
    the real ``requests.Response`` API that a drop-in replacement needs:
    ``status_code``, ``text``, ``content``, ``headers``, ``url``, and
    ``json()``.
    """

    def __init__(self, scrape_result: Dict[str, Any], request_url: str):
        self._result = scrape_result
        self.status_code: int = int(scrape_result.get("status_code") or 0)
        self.text: str = scrape_result.get("content") or ""
        self.headers: Dict[str, str] = scrape_result.get("headers") or {}
        # final_url reflects any redirect chain; fall back to the originally
        # requested URL when the scrape response doesn't report one.
        self.url: str = scrape_result.get("final_url") or request_url

    @property
    def content(self) -> bytes:
        """Raw response body as bytes (UTF-8 encoded), like ``requests``."""
        return self.text.encode("utf-8")

    @property
    def ok(self) -> bool:
        """``True`` for 2xx/3xx status codes, matching ``requests.Response.ok``."""
        return self.status_code < 400

    def json(self, **kwargs: Any) -> Any:
        """Parse the response body as JSON.

        Raises:
            json.JSONDecodeError: If the body is not valid JSON — matches
                real ``requests.Response.json()`` behavior (does not swallow
                the error).
        """
        return _json.loads(self.text, **kwargs)

    def raise_for_status(self) -> None:
        """Raise :class:`AlterLabHTTPError` if the status code indicates an error.

        AlterLab's own richer exceptions (`AlterLabAPIError` and subclasses)
        are raised earlier, during the request itself, for transport/API-level
        failures. This method covers the remaining case: the target site
        itself returned a 4xx/5xx status through a successful scrape.
        ``AlterLabHTTPError`` is a subclass of ``AlterLabAPIError``, so it is
        caught by the same ``except AlterLabAPIError`` handlers.
        """
        if 400 <= self.status_code:
            raise AlterLabHTTPError(
                self.status_code, f"{self.status_code} Error for url: {self.url}"
            )

    def __repr__(self) -> str:
        return f"<Response [{self.status_code}]>"


def configure(api_key: str, **kwargs: Any) -> None:
    """Explicitly configure the module-level client.

    Args:
        api_key: AlterLab API key. Overrides ``ALTERLAB_API_KEY`` env var.
        **kwargs: Additional keyword arguments forwarded to
            :class:`alterlab.client.AlterLabSync` (e.g. ``base_url``,
            ``timeout``, ``max_retries``).
    """
    global _client, _configured_api_key
    _configured_api_key = api_key
    _client = AlterLabSync(api_key=api_key, **kwargs)


def _get_client() -> AlterLabSync:
    """Return the module-level singleton client, creating it lazily.

    Raises:
        AlterLabValidationError: If no API key was provided via configure() and
            ALTERLAB_API_KEY is not set in the environment.
    """
    global _client
    if _client is not None:
        return _client

    api_key = _configured_api_key or os.environ.get(_ENV_API_KEY)
    if not api_key:
        raise AlterLabValidationError(
            "AlterLab API key not configured. Set the ALTERLAB_API_KEY "
            "environment variable, or call alterlab.requests.configure(api_key=...) "
            "before making a request."
        )
    _client = AlterLabSync(api_key=api_key)
    return _client


def _merge_params(url: str, params: Optional[Dict[str, Any]]) -> str:
    """URL-encode `params` and append to `url`, preserving any existing query string."""
    if not params:
        return url
    split = urlsplit(url)
    existing_qs = split.query
    new_qs = urlencode(params, doseq=True)
    merged_qs = f"{existing_qs}&{new_qs}" if existing_qs else new_qs
    return urlunsplit(
        (split.scheme, split.netloc, split.path, merged_qs, split.fragment)
    )


def _prepare_body(
    json: Optional[Any],
    data: Optional[Union[Dict[str, Any], str, bytes]],
    headers: Optional[Dict[str, str]],
) -> "tuple[Optional[str], Optional[str]]":
    """Translate requests-style json=/data= into AlterLab's body/content_type.

    Returns:
        (body, content_type) tuple. Either may be None.
    """
    # Caller-supplied Content-Type header (case-insensitive) wins over the
    # inferred default *only* when it's a value the API actually accepts for
    # the `content_type` relay parameter. An unsupported value (e.g.
    # "text/csv") is never forwarded as `content_type` — that param is a
    # Literal-typed selector for AlterLab's own relay serialization, not an
    # arbitrary passthrough, and the API rejects unknown values with 422/415.
    # The header itself is untouched here and still reaches the target site
    # via the `headers` dict forwarded separately in `request()` — so the
    # caller's original Content-Type header is always preserved regardless
    # of what this function returns.
    explicit_content_type = None
    if headers:
        for key, value in headers.items():
            if key.lower() == "content-type":
                if value in _ALLOWED_CONTENT_TYPES:
                    explicit_content_type = value
                break

    if json is not None:
        return _json.dumps(json), explicit_content_type or "application/json"

    if data is not None:
        if isinstance(data, dict):
            return urlencode(data, doseq=True), (
                explicit_content_type or "application/x-www-form-urlencoded"
            )
        if isinstance(data, bytes):
            return data.decode("utf-8"), explicit_content_type or "text/plain"
        return str(data), explicit_content_type or "text/plain"

    return None, explicit_content_type


def request(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Any] = None,
    data: Optional[Union[Dict[str, Any], str, bytes]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> Response:
    """Make a ``requests``-style HTTP request through AlterLab's scraping pipeline.

    Matches the call signature of ``requests.request`` for the parameters
    that map cleanly onto AlterLab's ``/api/v1/scrape`` endpoint. Extra
    keyword arguments are forwarded to
    :meth:`alterlab.client.AlterLab.scrape` (e.g. ``advanced``,
    ``cost_controls``, ``mode``), so advanced AlterLab features remain
    reachable without leaving the ``requests``-compatible call shape.

    Args:
        method: HTTP method (``"GET"``, ``"POST"``, ``"PUT"``, ``"PATCH"``,
            ``"DELETE"``).
        url: Target URL.
        params: Query parameters to URL-encode and append to ``url``.
        json: JSON-serializable body — sets ``Content-Type: application/json``.
        data: Form dict, string, or bytes body.
        headers: Custom headers forwarded to the target site.
        timeout: Request timeout in seconds.
        **kwargs: Forwarded to ``AlterLabSync.scrape()`` (e.g. ``advanced``,
            ``cost_controls``, ``mode``, ``sync``).

    Returns:
        A :class:`Response` object.

    Raises:
        alterlab.AlterLabAPIError: On API/transport errors (propagates
            unmodified — not wrapped in a requests-style exception).
    """
    full_url = _merge_params(url, params)
    body, content_type = _prepare_body(json, data, headers)

    scrape_kwargs: Dict[str, Any] = dict(kwargs)
    if headers is not None:
        scrape_kwargs["headers"] = headers
    if timeout is not None:
        scrape_kwargs["timeout"] = int(timeout)
    if body is not None:
        scrape_kwargs["body"] = body
    if content_type is not None:
        scrape_kwargs["content_type"] = content_type

    client = _get_client()
    result = client.scrape(full_url, method=method.upper(), **scrape_kwargs)
    return Response(result, full_url)


def get(url: str, **kwargs: Any) -> Response:
    """``requests.get``-compatible GET request. See :func:`request`."""
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> Response:
    """``requests.post``-compatible POST request. See :func:`request`."""
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> Response:
    """``requests.put``-compatible PUT request. See :func:`request`."""
    return request("PUT", url, **kwargs)


def patch(url: str, **kwargs: Any) -> Response:
    """``requests.patch``-compatible PATCH request. See :func:`request`."""
    return request("PATCH", url, **kwargs)


def delete(url: str, **kwargs: Any) -> Response:
    """``requests.delete``-compatible DELETE request. See :func:`request`."""
    return request("DELETE", url, **kwargs)
