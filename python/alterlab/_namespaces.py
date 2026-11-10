"""MCP-parity namespaces for the async client (#40286).

Thin typed wrappers over REST routes the MCP server also exposes, so SDK users
do not drop to raw REST or a separate MCP connector. Each namespace holds the
client and calls its retrying request helper; nothing here files feedback or
tickets on its own (``on_unexpected_response`` only notifies the caller).
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from urllib.parse import quote

if TYPE_CHECKING:
    from alterlab.client import AlterLab

# Called with {"method", "path", "status_code", "reason"} when a response is not
# the JSON object/array the route documents. Opt-in; default is no hook.
UnexpectedResponseHook = Callable[[Dict[str, Any]], None]

SCRAPE_ISSUE_TYPES = (
    "captcha_page",
    "incomplete_scrape",
    "blocked",
    "wrong_content",
    "slow_response",
    "extraction_error",
    "encoding_error",
    "other",
)


def _seg(value: str) -> str:
    return quote(str(value), safe="")


def _clean(**fields: Any) -> Dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None}


class _Namespace:
    def __init__(self, client: "AlterLab"):
        self._client = client

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        kwargs: Dict[str, Any] = {}
        if params:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        response = await self._client._request_with_retry(method, path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
            reason = None if isinstance(data, (dict, list)) else "not a JSON object"
        except ValueError:
            data, reason = response.text, "body is not JSON"
        if reason:
            hook = getattr(self._client, "on_unexpected_response", None)
            if hook is not None:
                hook(
                    {
                        "method": method,
                        "path": path,
                        "status_code": response.status_code,
                        "reason": reason,
                    }
                )
        return data


class AccountNamespace(_Namespace):
    """``client.account`` — balance and usage."""

    async def balance(self) -> Dict[str, Any]:
        """Wallet balance (``GET /api/v1/billing/balance``)."""
        return await self._call("GET", "/api/v1/billing/balance")

    async def usage(self) -> Dict[str, Any]:
        """Usage statistics (``GET /api/v1/usage``)."""
        return await self._call("GET", "/api/v1/usage")


class SupportNamespace(_Namespace):
    """``client.support`` — file a support ticket (``POST /api/v1/agent/support-ticket``)."""

    async def ticket(
        self,
        subject: str,
        body: str,
        category_slug: Optional[str] = None,
        on_behalf_of_user: bool = True,
        tool_name: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open a real support ticket. Only call when the user asked for help."""
        payload = _clean(
            subject=subject[:200],
            body=body[:5000],
            category_slug=category_slug,
            on_behalf_of_user=on_behalf_of_user,
            tool_name=tool_name,
            job_id=job_id,
        )
        return await self._call("POST", "/api/v1/agent/support-ticket", body=payload)


class JobsNamespace(_Namespace):
    """``client.jobs`` — report or explain a job."""

    async def report(
        self,
        job_id: str,
        issue_type: str,
        description: Optional[str] = None,
        expected_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Report a bad scrape result (``POST /api/v1/feedback/scrape``)."""
        if issue_type not in SCRAPE_ISSUE_TYPES:
            raise ValueError(
                f"issue_type must be one of: {', '.join(SCRAPE_ISSUE_TYPES)}"
            )
        payload = _clean(
            job_id=job_id,
            issue_type=issue_type,
            description=description[:2000] if description else None,
            expected_content=expected_content[:1000] if expected_content else None,
        )
        return await self._call("POST", "/api/v1/feedback/scrape", body=payload)

    async def explain(self, job_id: str) -> Dict[str, Any]:
        """Why a job ended as it did (``GET /api/v1/jobs/{id}/explain``)."""
        return await self._call("GET", f"/api/v1/jobs/{_seg(job_id)}/explain")


class _Collection(_Namespace):
    _base = ""

    async def list(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        active_only: Optional[bool] = None,
    ) -> Any:
        params = _clean(limit=limit, offset=offset, active_only=active_only)
        return await self._call("GET", self._base, params=params)

    async def create(self, **fields: Any) -> Dict[str, Any]:
        return await self._call("POST", self._base, body=_clean(**fields))

    async def delete(self, resource_id: str) -> Any:
        return await self._call("DELETE", f"{self._base}/{_seg(resource_id)}")


class MonitorsNamespace(_Collection):
    """``client.monitors`` — ``/api/v1/monitors`` (name, url, check_interval, ...)."""

    _base = "/api/v1/monitors"


class SchedulesNamespace(_Collection):
    """``client.schedules`` — ``/api/v1/schedules`` (name, urls, cron, ...)."""

    _base = "/api/v1/schedules"


class StoreNamespace(_Namespace):
    """``client.store`` — Data Store listings (``/api/v1/listings``)."""

    async def search(
        self,
        q: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Any:
        params = _clean(q=q, category=category, limit=limit, offset=offset)
        return await self._call("GET", "/api/v1/listings", params=params)

    async def get(self, slug: str, version: Optional[str] = None) -> Any:
        return await self._call(
            "GET", f"/api/v1/listings/{_seg(slug)}", params=_clean(version=version)
        )

    async def quote(
        self,
        slug: str,
        max_results: Optional[int] = None,
        version: Optional[str] = None,
    ) -> Any:
        body = _clean(max_results=max_results, version=version)
        return await self._call(
            "POST", f"/api/v1/listings/{_seg(slug)}/quote", body=body
        )

    async def run(
        self,
        slug: str,
        input: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
        wait: bool = True,
        version: Optional[str] = None,
    ) -> Any:
        """Run a listing; this spends credits."""
        return await self._call(
            "POST",
            f"/api/v1/listings/{_seg(slug)}/run",
            params={"wait": str(wait).lower(), **_clean(version=version)},
            body=_clean(input=input or {}, max_results=max_results),
        )


class FeedsNamespace(_Namespace):
    """``client.feeds`` — scheduled listing feeds."""

    async def list(self, slug: str) -> Any:
        return await self._call("GET", f"/api/v1/listings/{_seg(slug)}/feeds")

    async def create(self, slug: str, **fields: Any) -> Any:
        return await self._call(
            "POST", f"/api/v1/listings/{_seg(slug)}/feeds", body=_clean(**fields)
        )

    async def update(self, slug: str, feed_id: str, **fields: Any) -> Any:
        return await self._call(
            "PATCH",
            f"/api/v1/listings/{_seg(slug)}/feeds/{_seg(feed_id)}",
            body=_clean(**fields),
        )

    async def delete(self, slug: str, feed_id: str) -> Any:
        return await self._call(
            "DELETE", f"/api/v1/listings/{_seg(slug)}/feeds/{_seg(feed_id)}"
        )

    async def deltas(
        self,
        feed_id: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Any:
        return await self._call(
            "GET",
            f"/api/v1/listings/feeds/{_seg(feed_id)}/deltas",
            params=_clean(page=page, page_size=page_size),
        )


class WorkflowsNamespace(_Namespace):
    """``client.workflows`` — run a saved workflow."""

    async def run(
        self, workflow_id: str, input_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        return await self._call(
            "POST",
            f"/api/v1/workflows/{_seg(workflow_id)}/run",
            body={"input_data": input_data or {}},
        )


class ParityMixin:
    """Top-level MCP-parity methods mixed into :class:`AlterLab`."""

    on_unexpected_response: Optional[UnexpectedResponseHook] = None

    def _init_parity(self: "AlterLab") -> None:  # type: ignore[misc]
        self.account = AccountNamespace(self)
        self.support = SupportNamespace(self)
        self.jobs = JobsNamespace(self)
        self.monitors = MonitorsNamespace(self)
        self.schedules = SchedulesNamespace(self)
        self.store = StoreNamespace(self)
        self.feeds = FeedsNamespace(self)
        self.workflows = WorkflowsNamespace(self)
        self._parity = _Namespace(self)

    async def support_ticket(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Alias of ``support.ticket()``."""
        return await self.support.ticket(*args, **kwargs)  # type: ignore[attr-defined]

    async def report_scrape(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Alias of ``jobs.report()``."""
        return await self.jobs.report(*args, **kwargs)  # type: ignore[attr-defined]

    async def pricing(self) -> Dict[str, Any]:
        """Public price list (``GET /api/v1/pricing``)."""
        return await self._parity._call("GET", "/api/v1/pricing")  # type: ignore[attr-defined]

    async def news(
        self,
        q: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        language: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """News search (``GET /api/v1/news``)."""
        params = _clean(
            q=q,
            category=category,
            source=source,
            language=language,
            since=since,
            limit=limit,
        )
        return await self._parity._call("GET", "/api/v1/news", params=params)  # type: ignore[attr-defined]

    async def keyword_ideas(self, **fields: Any) -> Any:
        """Keyword ideas (``POST /api/v1/serp/keyword-ideas``)."""
        return await self._parity._call(  # type: ignore[attr-defined]
            "POST", "/api/v1/serp/keyword-ideas", body=_clean(**fields)
        )

    async def serp(
        self,
        query: str,
        search_engine: Optional[str] = None,
        device: Optional[str] = None,
        country: Optional[str] = None,
        city: Optional[str] = None,
        language: Optional[str] = None,
        num_results: Optional[int] = None,
        page: Optional[int] = None,
        safe_search: Optional[bool] = None,
    ) -> Any:
        """Structured search results (``POST /api/v1/serp``)."""
        body = _clean(
            query=query,
            search_engine=search_engine,
            device=device,
            country=country,
            city=city,
            language=language,
            num_results=num_results,
            page=page,
            safe_search=safe_search,
        )
        return await self._parity._call("POST", "/api/v1/serp", body=body)  # type: ignore[attr-defined]

    async def ai_visibility(
        self, action: str, run_id: Optional[str] = None, **fields: Any
    ) -> Any:
        """AI-visibility ``check``/``quote`` (POST) or ``status``/``results`` (GET)."""
        base = "/api/v1/ai-visibility"
        call = self._parity._call  # type: ignore[attr-defined]
        if action in ("check", "quote"):
            return await call("POST", f"{base}/{action}", body=_clean(**fields))
        if action in ("status", "results") and run_id:
            suffix = "/results" if action == "results" else ""
            return await call("GET", f"{base}/runs/{_seg(run_id)}{suffix}")
        raise ValueError("action must be check|quote, or status|results with run_id")

    async def screenshot(
        self,
        url: str,
        wait_until: str = "networkidle",
        wait_for: Optional[str] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Render ``url`` and return the job with ``screenshot_url``."""
        advanced: Dict[str, Any] = {"render_js": True, "screenshot": True}
        if actions:
            advanced["actions"] = actions
        body = _clean(
            url=url,
            mode="js",
            sync=True,
            screenshot=True,
            wait_until=wait_until,
            wait_for=wait_for,
            advanced=advanced,
        )
        return await self._parity._call("POST", "/api/v1/scrape", body=body)  # type: ignore[attr-defined]


class SyncNamespace:
    """Runs an async namespace's coroutine methods on the sync client's loop."""

    def __init__(self, target: Any, run: Callable[[Any], Any]):
        self._target = target
        self._run = run

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            return self._run(attr(*args, **kwargs))

        call.__name__ = name
        call.__doc__ = attr.__doc__
        return call
