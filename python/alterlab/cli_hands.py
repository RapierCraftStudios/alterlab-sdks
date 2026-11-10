"""``alterlab hands``: connect a site, list sessions, start a task, answer a request (#39556)."""

import json
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .cli_data import emit
from .client import AlterLabError

POLL_S = 2.0
CONNECT_WAIT_S = 600


def add_parser(sub) -> None:
    hands = sub.add_parser("hands", help="Act on sites with your own sessions")
    cmds = hands.add_subparsers(dest="hands_command", required=True)

    connect = cmds.add_parser("connect", help="Ask the user to connect a site")
    connect.add_argument("site")
    connect.add_argument("--scope", action="append", help="Scope to request (max 2)")
    connect.add_argument("--reason", default="", help="Why access is needed")
    connect.add_argument(
        "--no-wait", action="store_true", help="Print the approval link and exit"
    )

    sessions = cmds.add_parser("sessions", help="List session handles")
    sessions.add_argument("--revoke", metavar="SESSION_ID", help="Revoke a session")

    run = cmds.add_parser("run", help="Start a Hands task for a recipe")
    run.add_argument("recipe")
    run.add_argument("--param", action="append", metavar="K=V", help="Recipe input")
    run.add_argument("--session", help="Session handle from `hands connect`")
    run.add_argument("--mode", choices=["read", "write"], default="read")

    schema = cmds.add_parser(
        "schema", help="Describe the task page's fields and actions"
    )
    schema.add_argument("task", help="Task id")

    answer = cmds.add_parser("answer", help="Answer a question or approval")
    answer.add_argument("task", nargs="?", help="Task id (omit with --pending)")
    answer.add_argument("--request", help="Request id to answer")
    answer.add_argument("--answer", help="Free-text answer")
    answer.add_argument("--approve", action="store_true")
    answer.add_argument("--deny", action="store_true")
    answer.add_argument(
        "--pending", action="store_true", help="List unanswered requests"
    )

    facts = cmds.add_parser("facts", help="Read or record evidence-backed facts")
    facts.add_argument("action", choices=["get", "history", "put", "confirm"])
    facts.add_argument("--subject", help="Whose fact, e.g. user or org.acme")
    facts.add_argument("--key", help="Namespaced key, e.g. user.address.home")
    facts.add_argument("--prefix", help="List facts whose key starts with this")
    facts.add_argument("--value", help="Value for put (JSON, or plain text)")
    facts.add_argument("--kind", default="text", help="Value type slug (put)")
    facts.add_argument(
        "--ttl", type=int, metavar="SECONDS", help="How long it stays fresh"
    )
    facts.add_argument("--system-of-record", help="Where the fact lives (put)")

    receipt = cmds.add_parser("receipt", help="Show or verify signed action receipts")
    receipt.add_argument("action", choices=["show", "verify"])
    receipt.add_argument("--task", help="Only receipts of this task id")
    receipt.add_argument("--id", help="Only this receipt id")

    delegate = cmds.add_parser(
        "delegate", help="Hand a goal to Hands: find, verify, execute"
    )
    delegate.add_argument(
        "action", choices=["create", "advance", "answer", "status", "events"]
    )
    delegate.add_argument("run", nargs="?", help="Run id (all actions but create)")
    delegate.add_argument("--goal", help="create: the goal in your own words")
    delegate.add_argument("--target-url", help="create: the page the run starts on")
    delegate.add_argument("--policy", help="create: approval-policy label")
    delegate.add_argument("--preview", action="store_true", help="create: never commit")
    delegate.add_argument("--facts", help="advance: JSON list of facts with sources")
    delegate.add_argument(
        "--act", help="advance: JSON batch {actions: [...]} to execute"
    )
    delegate.add_argument("--finish", action="store_true", help="advance: end the run")
    delegate.add_argument("--request", help="answer: the pending request id")
    delegate.add_argument("--approve", action="store_true")
    delegate.add_argument("--deny", action="store_true")
    delegate.add_argument("--answer", help="answer: the reply to a question")
    delegate.add_argument("--after", type=int, default=0, help="events: seq cursor")
    runs = cmds.add_parser("runs", help="Delegated multi-target and recurring runs")
    runs.add_argument("action", choices=["list", "show", "answer", "cancel"])
    runs.add_argument("id", nargs="?", help="Run id (show, cancel) or target id (answer)")
    runs.add_argument("--approve", action="store_true")
    runs.add_argument("--deny", action="store_true")


def parse_params(items: Optional[List[str]]) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise AlterLabError(f"--param expects k=v, got {item!r}")
        params[key] = value
    return params


def cmd_connect(args, client) -> int:
    body: Dict[str, Any] = {"site": args.site, "reason": args.reason}
    if args.scope:
        body["scopes"] = args.scope
    offer = client.hands_request("POST", "/connect", body)
    emit(offer)
    print(f"alterlab: {offer.get('user_prompt', offer.get('link'))}", file=sys.stderr)
    if args.no_wait:
        return 0
    deadline = time.monotonic() + CONNECT_WAIT_S
    while time.monotonic() < deadline:
        state = client.hands_request("GET", f"/connect/{offer['connect_id']}")
        if state.get("status") == "connected":
            emit(state)
            return 0
        if state.get("status") == "expired":
            raise AlterLabError("connect request expired")
        time.sleep(POLL_S)
    raise AlterLabError("timed out waiting for approval")


def cmd_sessions(args, client) -> int:
    if args.revoke:
        emit(client.hands_request("DELETE", f"/sessions/{args.revoke}"))
        return 0
    for item in client.hands_request("GET", "/sessions").get("sessions", []):
        emit(item)
    return 0


def cmd_run(args, client) -> int:
    params = parse_params(args.param)
    site = params.get("site", "")
    start_url = params.get("start_url") or (f"https://{site}" if site else "")
    if not start_url:
        raise AlterLabError("hands run needs --param start_url=<url> (or site=<host>)")
    detail = ", ".join(f"{k}={v}" for k, v in params.items())
    body: Dict[str, Any] = {
        "start_url": start_url,
        "mode": args.mode,
        "instruction": f"Run recipe {args.recipe} ({detail})"[:4000],
    }
    if args.session:
        body["session_id"] = args.session
    task = client.hands_request("POST", "/tasks", body)
    emit(task)
    print(
        f"alterlab: task started; answer requests with `alterlab hands answer {task.get('id', '<task>')}`",
        file=sys.stderr,
    )
    return 0


def cmd_schema(args, client) -> int:
    emit(client.hands_request("POST", f"/tasks/{args.task}/schema"))
    return 0


def cmd_answer(args, client) -> int:
    if args.pending or not args.request:
        path = f"/tasks/{args.task}/requests" if args.task else "/requests/pending"
        for item in client.hands_request("GET", path):
            emit(item)
        return 0
    if not args.task:
        raise AlterLabError("hands answer needs a task id")
    if args.approve and args.deny:
        raise AlterLabError("pass only one of --approve and --deny")
    decision = "approve" if args.approve else "deny" if args.deny else None
    if not (decision or args.answer):
        raise AlterLabError("pass --answer TEXT, --approve or --deny")
    body = {"request_id": args.request, "decision": decision, "answer": args.answer}
    emit(client.hands_request("POST", f"/tasks/{args.task}/answer", body))
    return 0


def _fact_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def cmd_facts(args, client) -> int:
    if args.action in ("put", "confirm"):
        if not (args.subject and args.key):
            raise AlterLabError(f"hands facts {args.action} needs --subject and --key")
        if args.action == "confirm":
            emit(client.hands_request("POST", "/facts/confirm", _fact_ids(args)))
            return 0
        if args.value is None:
            raise AlterLabError("hands facts put needs --value")
        body = {**_fact_ids(args), "value": _fact_value(args.value), "kind": args.kind}
        if args.ttl:
            body["ttl_s"] = args.ttl
        if args.system_of_record:
            body["system_of_record"] = args.system_of_record
        emit(client.hands_request("PUT", "/facts", body))
        return 0
    if args.action == "history" and not (args.subject and args.key):
        raise AlterLabError("hands facts history needs --subject and --key")
    query = {"subject": args.subject, "key": args.key, "prefix": args.prefix}
    if args.action == "history":
        query["history"] = "true"
    qs = urlencode({k: v for k, v in query.items() if v})
    for item in client.hands_request("GET", f"/facts?{qs}" if qs else "/facts")[
        "facts"
    ]:
        emit(item)
    return 0


def _fact_ids(args) -> Dict[str, Any]:
    return {"subject": args.subject, "key": args.key}


def cmd_receipt(args, client) -> int:
    data = client.hands_request("GET", "/audit/export?include=receipts&format=json")
    rows = [
        r
        for r in (data.get("receipts") or [])
        if (not args.task or r.get("task_id") == args.task)
        and (not args.id or r.get("id") == args.id)
    ]
    if args.action == "show":
        for row in rows:
            emit(row)
        return 0
    bad = 0
    for row in rows:
        ok = bool(row.get("signature_valid"))
        bad += not ok
        emit(
            {"id": row.get("id"), "verdict": row.get("verdict"), "signature_valid": ok}
        )
    if not rows:
        print("alterlab: no receipts matched", file=sys.stderr)
        return 1
    return 1 if bad else 0


def _json_arg(raw: Optional[str], what: str) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        raise AlterLabError(f"--{what} must be valid JSON")


def cmd_delegate(args, client) -> int:
    """`hands delegate`: the run routes (#39854); every action prints the run's event schema."""
    if args.action == "create":
        if not args.goal:
            raise AlterLabError("hands delegate create needs --goal")
        body: Dict[str, Any] = {
            "goal": args.goal,
            "mode": "preview" if args.preview else "run",
        }
        if args.target_url:
            body["target"] = {"type": "url", "value": args.target_url}
        if args.policy:
            body["policy_ref"] = args.policy
        emit(client.hands_request("POST", "/runs", body))
        return 0
    if not args.run:
        raise AlterLabError(f"hands delegate {args.action} needs a run id")
    base = f"/runs/{args.run}"
    if args.action == "status":
        emit(client.hands_request("GET", base))
    elif args.action == "events":
        for event in client.hands_request("GET", f"{base}/events?after={args.after}"):
            emit(event)
    elif args.action == "advance":
        body = {"facts": _json_arg(args.facts, "facts") or [], "finish": args.finish}
        act = _json_arg(args.act, "act")
        if act:
            body["act"] = act
        emit(client.hands_request("POST", f"{base}/advance", body))
    else:
        if args.approve and args.deny:
            raise AlterLabError("pass only one of --approve and --deny")
        decision = "approve" if args.approve else "deny" if args.deny else None
        if not args.request or not (decision or args.answer):
            raise AlterLabError(
                "answer needs --request and --answer, --approve or --deny"
            )
        body = {"request_id": args.request, "decision": decision, "answer": args.answer}
        emit(client.hands_request("POST", f"{base}/answer", body))
    return 0


def cmd_runs(args, client) -> int:
    if args.action == "list":
        for item in client.hands_request("GET", "/runs").get("runs", []):
            emit(item)
        return 0
    if not args.id:
        raise AlterLabError(f"hands runs {args.action} needs an id")
    if args.action == "show":
        emit(client.hands_request("GET", f"/runs/{args.id}"))
    elif args.action == "cancel":
        emit(client.hands_request("POST", f"/runs/{args.id}/cancel", {}))
    else:
        if args.approve == args.deny:
            raise AlterLabError("pass exactly one of --approve and --deny")
        body = {"approved": args.approve}
        emit(client.hands_request("POST", f"/runs/targets/{args.id}/answer", body))
    return 0


COMMANDS = {
    "connect": cmd_connect,
    "sessions": cmd_sessions,
    "run": cmd_run,
    "schema": cmd_schema,
    "answer": cmd_answer,
    "facts": cmd_facts,
    "receipt": cmd_receipt,
    "delegate": cmd_delegate,
    "runs": cmd_runs,
}


def run(args, client) -> int:
    return COMMANDS[args.hands_command](args, client)
