"""``alterlab run`` commands for the beta agent runs API (#39407).

Thin wrappers over ``/api/v1/runs``: the API owns budget
enforcement, idempotency and the beta gate. Output is NDJSON on stdout like the other data
commands; ``stream`` resumes with ``Last-Event-ID`` when the connection drops.
"""

import json
import sys
from typing import Any, Dict, Iterator, Optional
from urllib.parse import quote

import httpx

from .cli_data import emit
from .client import AlterLabError, AlterLabSync

MAX_RECONNECTS = 3


def _http(
    client: AlterLabSync, transport: Optional[httpx.BaseTransport] = None
) -> httpx.Client:
    inner = client._client
    return httpx.Client(
        base_url=inner.base_url,
        headers={"X-API-Key": inner.api_key, "Content-Type": "application/json"},
        timeout=httpx.Timeout(30.0, read=None),
        transport=transport,
    )


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    if not isinstance(detail, str):
        detail = json.dumps(detail)
    raise AlterLabError(f"HTTP {resp.status_code}: {detail}")


def _load_plan(source: str, stdin=None) -> Dict[str, Any]:
    try:
        text = (stdin or sys.stdin).read() if source == "-" else open(source).read()
        plan = json.loads(text)
    except (OSError, ValueError) as exc:
        raise AlterLabError(f"cannot read plan {source}: {exc}") from exc
    if not isinstance(plan, dict):
        raise AlterLabError("plan must be a JSON object")
    return plan


def parse_sse(lines: Iterator[str]) -> Iterator[Dict[str, Any]]:
    """Yield event envelopes from SSE lines; ``timeout`` and unparsable frames are skipped."""
    name, data = "message", []
    for line in lines:
        if line == "":
            if data and name != "timeout":
                try:
                    yield json.loads("\n".join(data))
                except ValueError:
                    pass
            name, data = "message", []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())


def _stream(http: httpx.Client, run_id: str, last_event_id: Optional[int]) -> int:
    path = f"/api/v1/runs/{quote(run_id, safe='')}/events"
    last, failures = last_event_id, 0
    while True:
        headers = {"Accept": "text/event-stream"}
        if last is not None:
            headers["Last-Event-ID"] = str(last)
        try:
            with http.stream("GET", path, headers=headers) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    _raise_for(resp)
                for event in parse_sse(resp.iter_lines()):
                    emit(event)
                    last = event.get("seq", last)
            return 0
        except httpx.TransportError as exc:
            failures += 1
            if failures > MAX_RECONNECTS:
                raise AlterLabError(f"event stream lost after {last}: {exc}") from exc


def cmd_run(args, client: AlterLabSync, stdin=None, transport=None) -> int:
    action = args.run_command
    with _http(client, transport) as http:
        if action == "stream":
            return _stream(http, args.run_id, args.last_event_id)
        if action == "create":
            plan = _load_plan(args.plan, stdin)
            for key, flag in (
                ("max_credits", args.max_credits),
                ("webhook_url", args.webhook_url),
            ):
                if flag is not None:
                    plan[key] = flag
            if args.auto_approve:
                plan["auto_approve"] = True
            if args.dry_run:
                plan["dry_run"] = True
            headers = (
                {"Idempotency-Key": args.idempotency_key}
                if args.idempotency_key
                else {}
            )
            resp = http.post("/api/v1/runs", json=plan, headers=headers)
        else:
            path = f"/api/v1/runs/{quote(args.run_id, safe='')}"
            if action == "approve":
                body = {"max_credits": args.max_credits} if args.max_credits else None
                resp = http.post(path + "/approve", json=body)
            elif action == "cancel":
                resp = http.post(path + "/cancel")
            else:
                resp = http.get(path)
        _raise_for(resp)
        emit(resp.json())
    return 0
