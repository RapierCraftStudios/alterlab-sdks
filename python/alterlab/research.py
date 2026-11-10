"""Research jobs (``/api/v1/research``): start, poll, cancel, stream events, steer the plan.

Research runs on the caller's own model key (BYOK): a missing key is rejected by the API with
``byok_key_required`` and nothing is charged. Mixed into :class:`alterlab.client.AlterLab`.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

# A job in one of these states will not change without caller action. ``awaiting_approval`` is
# included so waiting on a ``plan_first`` job returns the plan instead of blocking forever.
RESEARCH_SETTLED_STATUSES = frozenset(
    {"awaiting_approval", "completed", "completed_partial", "failed", "cancelled"}
)

_RESEARCH_OPTIONS = (
    "effort",
    "max_cost_microcents",
    "max_tool_calls",
    "max_runtime_seconds",
    "max_depth",
    "max_sources",
    "output",
    "citation_format",
    "output_length",
    "criteria",
    "min_sources",
    "sources",
    "output_schema",
    "files",
    "tools",
    "plan_first",
    "webhook",
    "provider",
    "model",
)


def parse_sse_events(text: str) -> List[Dict[str, Any]]:
    """Parse a ``text/event-stream`` body into ``{id, event, data}`` dicts (data is JSON-decoded)."""
    events: List[Dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event: Dict[str, Any] = {}
        data_lines: List[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                data_lines.append(value)
            elif field in ("id", "event"):
                event[field] = value
        if data_lines:
            raw = "\n".join(data_lines)
            try:
                event["data"] = json.loads(raw)
            except ValueError:
                event["data"] = raw
        if event:
            events.append(event)
    return events


class ResearchMixin:
    """Research job methods; expects ``_request_with_retry`` from the host client."""

    async def research(self, query: str, **options: Any) -> Dict[str, Any]:
        """Start a research job and return the job (``id``, ``status``, ``budget``, ...).

        Args:
            query: Research question (max 4000 characters)
            **options: Any request field: ``effort`` (lite|standard|deep|exhaustive|frontier),
                ``max_cost_microcents``, ``max_tool_calls``, ``max_runtime_seconds``,
                ``max_depth``, ``max_sources``, ``output`` (json|report|both),
                ``citation_format``, ``output_length``, ``criteria``, ``min_sources``,
                ``sources``, ``output_schema``, ``files``, ``tools``, ``plan_first``,
                ``webhook``, ``provider``, ``model``

        Returns:
            The queued job. Poll with ``get_research`` or block with ``wait_for_research``.

        Raises:
            ValueError: On an unknown option
            AlterLabAPIError: On API errors, including ``byok_key_required``
        """
        unknown = sorted(set(options) - set(_RESEARCH_OPTIONS))
        if unknown:
            raise ValueError(f"research() got unknown option(s): {', '.join(unknown)}")
        payload: Dict[str, Any] = {"query": query}
        payload.update({k: v for k, v in options.items() if v is not None})
        response = await self._request_with_retry(
            "POST", "/api/v1/research", json=payload
        )
        return response.json()

    async def get_research(self, job_id: str) -> Dict[str, Any]:
        """Return a research job: status, cost, coverage, warnings and (when done) the result."""
        response = await self._request_with_retry("GET", f"/api/v1/research/{job_id}")
        return response.json()

    async def cancel_research(self, job_id: str) -> Dict[str, Any]:
        """Cancel a queued or running research job and return it."""
        response = await self._request_with_retry(
            "POST", f"/api/v1/research/{job_id}/cancel"
        )
        return response.json()

    async def wait_for_research(
        self, job_id: str, *, poll_interval: float = 2.0, timeout: float = 600.0
    ) -> Dict[str, Any]:
        """Poll until the job is completed, completed_partial, failed, cancelled or awaiting
        approval, and return it.

        Raises:
            AlterLabTimeoutError: When ``timeout`` elapses first (the job keeps running)
        """
        from alterlab.client import AlterLabTimeoutError

        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_research(job_id)
            if job.get("status") in RESEARCH_SETTLED_STATUSES:
                return job
            if time.monotonic() + poll_interval > deadline:
                raise AlterLabTimeoutError(
                    f"Research job {job_id} still {job.get('status')} after {timeout}s"
                )
            await asyncio.sleep(poll_interval)

    async def research_events(
        self, job_id: str, *, last_event_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return the job's progress events as ``{id, event, data}`` dicts.

        The stream closes after the final ``research.<status>`` event. Pass the last ``id`` you
        saw as ``last_event_id`` to receive only the events you missed.
        """
        headers = {"Last-Event-ID": last_event_id} if last_event_id else None
        response = await self._request_with_retry(
            "GET", f"/api/v1/research/{job_id}/events", headers=headers
        )
        return parse_sse_events(response.text)

    async def get_research_plan(self, job_id: str) -> Dict[str, Any]:
        """Return the plan of a ``plan_first`` job."""
        response = await self._request_with_retry(
            "GET", f"/api/v1/research/{job_id}/plan"
        )
        return response.json()

    async def update_research_plan(
        self, job_id: str, plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Replace the plan of a job awaiting approval."""
        response = await self._request_with_retry(
            "PUT", f"/api/v1/research/{job_id}/plan", json={"plan": plan}
        )
        return response.json()

    async def approve_research(
        self, job_id: str, plan: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Approve the plan (optionally replacing it) and start the run."""
        kwargs: Dict[str, Any] = {"json": {"plan": plan}} if plan is not None else {}
        response = await self._request_with_retry(
            "POST", f"/api/v1/research/{job_id}/approve", **kwargs
        )
        return response.json()
