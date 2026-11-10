"""Account-free local tools: detect, doctor, md, robots (#38951).

Nothing here talks to AlterLab: pages are fetched directly from the target.
"""

import json
import re
import ssl
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

# What a current desktop Chrome sends on a top-level navigation, in order.
BROWSER_BASELINE_HEADERS = [
    "host",
    "connection",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "upgrade-insecure-requests",
    "user-agent",
    "accept",
    "sec-fetch-site",
    "sec-fetch-mode",
    "sec-fetch-user",
    "sec-fetch-dest",
    "accept-encoding",
    "accept-language",
]
AI_CRAWLERS = [
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "anthropic-ai",
    "CCBot",
    "Google-Extended",
    "PerplexityBot",
    "Bytespider",
    "Applebot-Extended",
]
FIX_HINT = "alterlab scrape <url>  (https://alterlab.io/docs)"


def load_signatures() -> Dict[str, Dict[str, List[str]]]:
    return json.loads((Path(__file__).parent / "vendor_signatures.json").read_text())


def detect_from(
    headers: Dict[str, str], cookies: List[str], body: str = ""
) -> List[Dict[str, Any]]:
    """Match response signals against the bundled vendor signatures."""
    hdr = {k.lower(): v.lower() for k, v in headers.items()}
    body_l = body.lower()
    found = []
    for vendor, sig in load_signatures().items():
        evidence: List[str] = []
        for tok in sig.get("cookies", []):
            if any(c.lower().startswith(tok.lower().rstrip("*")) for c in cookies):
                evidence.append(f"cookie:{tok}")
        for tok in sig.get("headers", []):
            name, _, value = tok.partition(":")
            name, value = name.strip().rstrip("*"), value.strip()
            if any(h.startswith(name) and value in v for h, v in hdr.items()):
                evidence.append(f"header:{tok}")
        for url in sig.get("sensor_urls", []):
            if url and url.lower() in body_l:
                evidence.append(f"script:{url}")
        if evidence:
            found.append({"vendor": vendor, "evidence": evidence})
    return found


def _get(url: str, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    with httpx.Client(follow_redirects=True, timeout=20) as http:
        return http.get(url, headers=headers)


def detect(url: str) -> Dict[str, Any]:
    resp = _get(url)
    cookies = [c.name for c in resp.cookies.jar]
    vendors = detect_from(dict(resp.headers), cookies, resp.text)
    return {
        "url": url,
        "status": resp.status_code,
        "vendors": vendors,
        "protected": bool(vendors),
    }


def _tls_info(url: str) -> Dict[str, Any]:
    import socket

    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return {}
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    with socket.create_connection(
        (parts.hostname, parts.port or 443), timeout=10
    ) as raw:
        with ctx.wrap_socket(raw, server_hostname=parts.hostname) as tls:
            cipher = tls.cipher()
            return {
                "tls_version": tls.version(),
                "cipher": cipher[0] if cipher else None,
                "alpn": tls.selected_alpn_protocol(),
                "client_library": ssl.OPENSSL_VERSION,
            }


def doctor(url: str) -> Dict[str, Any]:
    """Fetch locally and report the signals a protected site sees from this client."""
    resp = _get(url)
    sent = [k.lower() for k in resp.request.headers.keys()]
    missing = [h for h in BROWSER_BASELINE_HEADERS if h not in sent]
    ua = resp.request.headers.get("user-agent", "")
    findings = []
    if missing:
        findings.append("missing browser headers: " + ", ".join(missing))
    if not ua or "mozilla" not in ua.lower():
        findings.append(f"non-browser User-Agent: {ua!r}")
    if resp.http_version != "HTTP/2":
        findings.append(
            f"negotiated {resp.http_version}; browsers use HTTP/2 on most sites"
        )
    try:
        tls = _tls_info(url)
    except (OSError, ssl.SSLError):
        tls = {}
    if tls:
        findings.append(
            f"TLS ClientHello comes from {tls['client_library']}, not a browser (JA3/JA4 differ)"
        )
    vendors = detect_from(
        dict(resp.headers), [c.name for c in resp.cookies.jar], resp.text
    )
    blocked = resp.status_code in (401, 403, 429, 503) or bool(vendors)
    return {
        "url": url,
        "status": resp.status_code,
        "blocked": blocked,
        "vendors": vendors,
        "http_version": resp.http_version,
        "request_header_order": sent,
        "baseline_header_order": BROWSER_BASELINE_HEADERS,
        "tls": tls,
        "findings": findings,
        "fix": FIX_HINT,
    }


class _Md(HTMLParser):
    SKIP = {"script", "style", "noscript", "head", "template", "svg"}

    def __init__(self, base: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.skip = 0
        self.base = base
        self.href: List[Optional[str]] = []
        self.lists: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "article", "tr", "br"):
            self.out.append("\n\n" if tag != "br" else "\n")
        elif tag in ("ul", "ol"):
            self.lists.append(tag)
        elif tag == "li":
            self.out.append(
                "\n" + ("1. " if self.lists and self.lists[-1] == "ol" else "- ")
            )
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code":
            self.out.append("`")
        elif tag == "a":
            self.href.append(urljoin(self.base, a["href"]) if a.get("href") else None)
            self.out.append("[")
        elif tag == "img" and a.get("src"):
            self.out.append(f"![{a.get('alt') or ''}]({urljoin(self.base, a['src'])})")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code":
            self.out.append("`")
        elif tag == "a" and self.href:
            href = self.href.pop()
            self.out.append(f"]({href})" if href else "]")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def html_to_markdown(html: str, base: str = "") -> str:
    parser = _Md(base)
    parser.feed(html)
    text = "".join(parser.out)
    text = re.sub(r"\[\]\([^)]*\)", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def md(source: str) -> str:
    """HTML to markdown: offline for files, a direct fetch for URLs."""
    if re.match(r"^https?://", source):
        return html_to_markdown(_get(source).text, source)
    return html_to_markdown(Path(source).read_text(errors="replace"))


def parse_robots(text: str) -> Dict[str, Any]:
    groups: Dict[str, List[Tuple[str, str]]] = {}
    sitemaps: List[str] = []
    agents: List[str] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not last_was_agent:
                agents = []
            agents.append(value)
            groups.setdefault(value.lower(), [])
            last_was_agent = True
            continue
        last_was_agent = False
        if key == "sitemap":
            sitemaps.append(value)
        elif key in ("allow", "disallow"):
            for agent in agents:
                groups[agent.lower()].append((key, value))
    ai = {}
    for bot in AI_CRAWLERS:
        rules = groups.get(bot.lower(), groups.get("*", []))
        blocked = any(k == "disallow" and v == "/" for k, v in rules)
        ai[bot] = "blocked" if blocked else "allowed"
    return {"ai_crawlers": ai, "sitemaps": sitemaps, "user_agents": sorted(groups)}


def robots(url: str) -> Dict[str, Any]:
    parts = urlparse(url if "//" in url else "https://" + url)
    origin = f"{parts.scheme}://{parts.netloc}"
    rob = _get(origin + "/robots.txt")
    llms = _get(origin + "/llms.txt")
    result = {"origin": origin, "robots_status": rob.status_code}
    result.update(parse_robots(rob.text if rob.status_code == 200 else ""))
    result["llms_txt"] = (
        llms.status_code == 200 and "<html" not in llms.text[:200].lower()
    )
    return result
