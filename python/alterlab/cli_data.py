"""Data commands for the ``alterlab`` CLI: NDJSON on stdout, cost on stderr (#38951)."""

import base64
import json
import sys
from typing import Any, Dict, Iterable, List, Optional

import httpx

from . import cli_local
from .cli_auth import load_key
from .client import AdvancedOptions, AlterLabError, AlterLabSync

FORMATS = {"md": "markdown", "markdown": "markdown", "json": "json", "html": "html"}
BLOCK_STATUSES = (401, 403, 429, 503)


class CostCapError(Exception):
    pass


def emit(obj: Any, out=None) -> None:
    print(json.dumps(obj, default=str, separators=(",", ":")), file=out or sys.stdout)


def client_from_env() -> AlterLabSync:
    key = load_key()
    if not key:
        raise AlterLabError(
            "not logged in: run `alterlab login` or set ALTERLAB_API_KEY"
        )
    return AlterLabSync(api_key=key)


def _usd(resp: Dict[str, Any]) -> Optional[float]:
    for key in ("estimated_cost_usd", "cost_usd"):
        if isinstance(resp.get(key), (int, float)):
            return float(resp[key])
    micro = resp.get("estimated_cost_microcents")
    if micro is None:
        billing = resp.get("billing") or {}
        micro = billing.get("final_cost_microcents", billing.get("total_credits"))
    return micro / 1_000_000 if isinstance(micro, (int, float)) else None


def report_cost(resp: Dict[str, Any], label: str = "cost") -> None:
    usd = _usd(resp)
    shown = f"${usd:.4f}" if usd is not None else "unknown"
    print(f"alterlab: {label} {shown}", file=sys.stderr)


def _estimate(
    client: AlterLabSync, kind: str, url: str, pages: int = 1
) -> Dict[str, Any]:
    """Quote a command up front. Only scrape-priced commands can be quoted."""
    if kind in ("search", "map"):
        return {"estimated_cost_usd": None, "note": f"{kind} has no estimator"}
    quote = client.estimate_cost(url)
    usd = _usd(quote)
    if usd is not None and pages > 1:
        quote = dict(quote, estimated_cost_usd=usd * pages, pages=pages)
    return quote


def _gate(client, kind, url, args, pages: int = 1) -> bool:
    """Handle --estimate / --max-cost. Returns True when the command must not run."""
    if not (args.estimate or args.max_cost is not None):
        return False
    quote = _estimate(client, kind, url, pages)
    usd = _usd(quote)
    if args.estimate:
        emit(quote)
        report_cost(quote, "estimated")
        return True
    if usd is None:
        raise CostCapError(
            f"cannot enforce --max-cost for `{kind}`: no estimate available"
        )
    if usd > args.max_cost:
        raise CostCapError(
            f"estimated ${usd:.4f} exceeds --max-cost ${args.max_cost:.4f}"
        )
    return False


def _items(resp: Dict[str, Any], keys: Iterable[str]) -> List[Any]:
    for key in keys:
        if isinstance(resp.get(key), list):
            return resp[key]
    return [resp]


def _content(resp: Dict[str, Any], fmt: str) -> Any:
    content = resp.get("content")
    if isinstance(content, dict):
        return content.get(
            fmt, content.get("markdown") or content.get("text") or content
        )
    return content


def _parse_selects(selects: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    if not selects:
        return None
    props = {}
    for item in selects:
        name, sep, selector = item.partition("=")
        if not sep or not name or not selector:
            raise AlterLabError(f"--select expects name=css, got {item!r}")
        props[name] = {"type": "string", "selector": selector}
    return {"type": "object", "properties": props}


def cmd_scrape(args, client: AlterLabSync) -> int:
    if _gate(client, "scrape", args.url, args):
        return 0
    fmt = FORMATS[args.format]
    resp = client.scrape(
        args.url,
        mode="js" if args.render else "auto",
        formats=[fmt],
        extraction_schema=_parse_selects(args.select),
    )
    report_cost(resp)
    if args.format == "json" or args.select:
        emit(resp)
    else:
        print(_content(resp, fmt))
    return 0


def cmd_extract(args, client: AlterLabSync) -> int:
    if _gate(client, "extract", args.url, args):
        return 0
    resp = client.scrape(args.url, formats=["json"], extraction_profile=args.profile)
    report_cost(resp)
    emit(resp)
    return 0


def cmd_screenshot(args, client: AlterLabSync) -> int:
    if _gate(client, "screenshot", args.url, args):
        return 0
    resp = client.scrape(
        args.url, mode="js", advanced=AdvancedOptions(render_js=True, screenshot=True)
    )
    report_cost(resp)
    shot = resp.get("screenshot_url") or resp.get("screenshot")
    if not shot:
        raise AlterLabError("no screenshot returned")
    if str(shot).startswith("http"):
        data = httpx.get(shot, timeout=60).content
    else:
        data = base64.b64decode(str(shot).split(",")[-1])
    with open(args.output, "wb") as fh:
        fh.write(data)
    emit({"url": args.url, "output": args.output, "bytes": len(data)})
    return 0


def cmd_crawl(args, client: AlterLabSync) -> int:
    if _gate(client, "crawl", args.url, args, pages=args.max):
        return 0
    resp = client.crawl_and_wait(args.url, max_pages=args.max)
    report_cost(resp)
    for page in _items(resp, ("pages", "results", "data")):
        emit(page)
    return 0


def cmd_map(args, client: AlterLabSync) -> int:
    if _gate(client, "map", args.url, args):
        return 0
    resp = client.map(args.url)
    report_cost(resp)
    for item in _items(resp, ("urls", "links")):
        emit(item if isinstance(item, dict) else {"url": item})
    return 0


def cmd_search(args, client: AlterLabSync) -> int:
    if _gate(client, "search", args.query, args):
        return 0
    resp = client.search(args.query, scrape_results=args.content)
    report_cost(resp)
    for item in _items(resp, ("results",)):
        emit(item)
    return 0


def cmd_batch(args, client: AlterLabSync, stdin=None) -> int:
    urls = [ln.strip() for ln in (stdin or sys.stdin) if ln.strip()]
    if not urls:
        raise AlterLabError("no URLs on stdin")
    if args.estimate or args.max_cost is not None:
        quote = _estimate(client, "batch", urls[0], pages=len(urls))
        usd = _usd(quote)
        if args.estimate:
            emit(quote)
            report_cost(quote, "estimated")
            return 0
        if usd is None or usd > args.max_cost:
            raise CostCapError(
                f"estimated {usd} exceeds --max-cost ${args.max_cost:.4f}"
            )
    resp = client.batch_scrape([{"url": u} for u in urls])
    report_cost(resp)
    for item in _items(resp, ("jobs", "results")):
        emit(item)
    return 0


def direct_blocked(resp: httpx.Response) -> bool:
    if resp.status_code in BLOCK_STATUSES or not resp.text.strip():
        return True
    return bool(cli_local.detect_from(dict(resp.headers), [], resp.text)) and (
        resp.status_code >= 400 or len(resp.text) < 2000
    )


def cmd_fetch(args, client_factory=None) -> int:
    """Direct fetch first; AlterLab only when blocked."""
    try:
        resp = httpx.get(args.url, follow_redirects=True, timeout=20)
        if not direct_blocked(resp):
            print(
                cli_local.html_to_markdown(resp.text, args.url)
                if args.format != "html"
                else resp.text
            )
            print("alterlab: fetched directly, cost $0", file=sys.stderr)
            return 0
    except httpx.HTTPError:
        pass
    print("alterlab: direct fetch blocked, falling back to AlterLab", file=sys.stderr)
    with (client_factory or client_from_env)() as client:
        return cmd_scrape(args, client)
