"""``alterlab`` command line: login, scrape/crawl/search, local tools, MCP, feedback."""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import (
    cli_auth,
    cli_data,
    cli_hands,
    cli_local,
    cli_routing,
    cli_runs,
    listings,
    mcp_stdio,
)
from .client import AlterLabError, AlterLabSync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alterlab")
    sub = parser.add_subparsers(dest="command", required=True)
    fb = sub.add_parser("feedback", help="Tell AlterLab what went wrong")
    fb.add_argument("--category", required=True, help="e.g. blocked, bug, docs")
    fb.add_argument("--message", required=True, help="What happened")
    fb.add_argument("--tried", help="What you tried")
    fb.add_argument("--expected", help="What you expected")
    fb.add_argument(
        "--job-id",
        default=os.environ.get("ALTERLAB_LAST_JOB_ID"),
        help="Job to attach (default: $ALTERLAB_LAST_JOB_ID)",
    )
    _add_commands(sub)
    return parser


def _add_run_commands(sub) -> None:
    run = sub.add_parser("run", help="Agent runs (beta): plan, approve, stream, result")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    create = run_sub.add_parser(
        "create", help="Create a run from a plan file (- for stdin)"
    )
    create.add_argument("plan")
    create.add_argument(
        "--max-credits", type=int, help="Hard credit budget (overrides the plan)"
    )
    create.add_argument("--auto-approve", action="store_true")
    create.add_argument(
        "--dry-run", action="store_true", help="Estimate only, store nothing"
    )
    create.add_argument("--webhook-url")
    create.add_argument("--idempotency-key")
    approve = run_sub.add_parser("approve", help="Approve a run and start it")
    approve.add_argument("run_id")
    approve.add_argument("--max-credits", type=int, help="New budget for the run")
    stream = run_sub.add_parser("stream", help="Print run events as NDJSON")
    stream.add_argument("run_id")
    stream.add_argument("--last-event-id", type=int, help="Resume after this seq")
    for name, helptext in (
        ("result", "State, spend and step summaries"),
        ("cancel", "Cancel and refund the unused budget"),
    ):
        run_sub.add_parser(name, help=helptext).add_argument("run_id")


def _add_commands(sub) -> None:
    cost = argparse.ArgumentParser(add_help=False)
    cost.add_argument(
        "--estimate", action="store_true", help="Print the quote and exit"
    )
    cost.add_argument(
        "--max-cost", type=float, metavar="USD", help="Hard spend cap in USD"
    )

    login = sub.add_parser("login", help="Sign in with a human-approved device flow")
    login.add_argument("--email", default=os.environ.get("ALTERLAB_EMAIL"))
    login.add_argument("--agent-name", default="alterlab-cli")
    login.add_argument("--base-url", default=cli_auth.DEFAULT_BASE_URL)

    for name, helptext in (
        ("scrape", "Scrape a URL"),
        ("fetch", "Direct fetch, AlterLab if blocked"),
    ):
        p = sub.add_parser(name, help=helptext, parents=[cost])
        p.add_argument("url")
        p.add_argument("-f", "--format", choices=["md", "json", "html"], default="md")
        p.add_argument("--render", action="store_true", help="Render JavaScript")
        p.add_argument("--select", action="append", metavar="NAME=CSS")
    for name, helptext in (
        ("map", "List a site's URLs"),
        ("screenshot", "Save a screenshot"),
    ):
        p = sub.add_parser(name, help=helptext, parents=[cost])
        p.add_argument("url")
        if name == "screenshot":
            p.add_argument("-o", "--output", default="screenshot.png")
    crawl = sub.add_parser("crawl", help="Crawl a site", parents=[cost])
    crawl.add_argument("url")
    crawl.add_argument("--max", type=int, default=50, help="Max pages")
    search = sub.add_parser("search", help="Web search", parents=[cost])
    search.add_argument("query")
    search.add_argument("--content", action="store_true", help="Include page content")
    extract = sub.add_parser(
        "extract", help="Selector-based extraction", parents=[cost]
    )
    extract.add_argument("url")
    extract.add_argument("--profile", default="auto")
    sub.add_parser("batch", help="Scrape URLs from stdin", parents=[cost])
    _add_run_commands(sub)

    for name, helptext in (
        ("detect", "Which anti-bot vendor protects a URL (no account)"),
        ("doctor", "Why is my scraper blocked? (no account)"),
        ("robots", "robots.txt, llms.txt and AI-crawler rules (no account)"),
        ("md", "HTML file or URL to markdown (no account)"),
    ):
        sub.add_parser(name, help=helptext).add_argument("target")
    sub.add_parser("mcp", help="Run a stdio MCP server")
    listings.add_parser(sub)
    skill = sub.add_parser("skill", help="Agent skills").add_subparsers(
        dest="skill_command", required=True
    )
    install = skill.add_parser("install", help="Install the AlterLab skill")
    install.add_argument(
        "--agent", default="claude", choices=["claude", "codex", "agents"]
    )
    cli_hands.add_parser(sub)
    routing = sub.add_parser(
        "routing-policy",
        help="Write the 'use AlterLab for web tasks' policy into the agent's instructions file",
    )
    routing.add_argument(
        "--agent", default="claude", choices=sorted(cli_routing.AGENT_FILES)
    )
    routing.add_argument(
        "--domains",
        help="Comma-separated domains to scope the policy to (default: all)",
    )
    routing.add_argument(
        "--dir", default=".", help="Project root holding the instructions file"
    )


DATA_COMMANDS = {
    "scrape": cli_data.cmd_scrape,
    "extract": cli_data.cmd_extract,
    "screenshot": cli_data.cmd_screenshot,
    "crawl": cli_data.cmd_crawl,
    "map": cli_data.cmd_map,
    "search": cli_data.cmd_search,
    "batch": cli_data.cmd_batch,
    "run": cli_runs.cmd_run,
}
LOCAL_COMMANDS = {
    "detect": cli_local.detect,
    "doctor": cli_local.doctor,
    "robots": cli_local.robots,
}


def _run(args) -> int:
    cmd = args.command
    if cmd == "login":
        if not args.email:
            print("alterlab: login needs --email (or $ALTERLAB_EMAIL)", file=sys.stderr)
            return 2
        return cli_auth.login(args.email, args.agent_name, args.base_url)
    if cmd in LOCAL_COMMANDS:
        cli_data.emit(LOCAL_COMMANDS[cmd](args.target))
        return 0
    if cmd == "md":
        sys.stdout.write(cli_local.md(args.target))
        return 0
    if cmd == "mcp":
        return mcp_stdio.serve()
    if cmd == "listings":
        return listings.dispatch(args, cli_data.emit)
    if cmd == "skill":
        print(f"installed: {mcp_stdio.skill_install(args.agent)}", file=sys.stderr)
        return 0
    if cmd == "routing-policy":
        domains = [d.strip() for d in (args.domains or "").split(",") if d.strip()]
        path = cli_routing.install_policy(args.agent, Path(args.dir), domains)
        print(f"wrote: {path}", file=sys.stderr)
        return 0
    if cmd == "fetch":
        return cli_data.cmd_fetch(args)
    if cmd == "hands":
        with cli_data.client_from_env() as client:
            return cli_hands.run(args, client)
    if cmd in DATA_COMMANDS:
        with cli_data.client_from_env() as client:
            return DATA_COMMANDS[cmd](args, client)
    raise AlterLabError(f"unknown command {cmd}")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "feedback":
        try:
            return _run(args)
        except (AlterLabError, cli_data.CostCapError) as exc:
            print(f"alterlab: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # network/IO failures: one clean line, no traceback
            print(f"alterlab: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    return _feedback(args)


def _feedback(args) -> int:
    try:
        with AlterLabSync() as client:
            result = client.feedback(
                args.category,
                args.tried,
                args.message,
                expected=args.expected,
                job_id=args.job_id,
            )
    except AlterLabError as exc:
        print(f"alterlab: {exc}", file=sys.stderr)
        return 1
    print(f"cluster_key: {result['cluster_key']}")
    print(f"status_url: {result['status_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
