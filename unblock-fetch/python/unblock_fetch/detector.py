"""Block detector: does a plain fetch result look blocked rather than served?"""

import re
from typing import Optional

_ALWAYS_BLOCK_STATUS = frozenset({403, 429})
_CHALLENGE_STATUS = frozenset({503})

_CHALLENGE_MARKERS = re.compile(
    r"just a moment|checking your browser|verify you are (?:a )?human|attention required"
    r"|access denied|captcha|are you a robot|unusual traffic|enable javascript and cookies"
    r"|px-captcha|challenge-platform|cf-chl|_incapsula_|datadome|geo\.captcha-delivery\.com"
    r"|hcaptcha|g-recaptcha|cf-turnstile",
    re.IGNORECASE,
)
_SCRIPT_OR_STYLE = re.compile(
    r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAGS = re.compile(r"<[^>]+>")
_JS_REQUIRED = re.compile(r"enable javascript|requires javascript", re.IGNORECASE)
_EMPTY_SHELL_MAX_CHARS = 80


def _visible_text(html: str) -> str:
    return " ".join(_TAGS.sub(" ", _SCRIPT_OR_STYLE.sub(" ", html)).split())


def detect_block(status_code: Optional[int], body: str) -> bool:
    """True for 403/429, a 503 or 2xx page carrying a challenge or CAPTCHA signature, or an
    empty JavaScript shell. A plain 404 or other error status is never a block."""
    body = body or ""
    if status_code in _ALWAYS_BLOCK_STATUS:
        return True
    if status_code in _CHALLENGE_STATUS:
        return bool(_CHALLENGE_MARKERS.search(body))
    if status_code is not None and not 200 <= status_code < 300:
        return False
    if _CHALLENGE_MARKERS.search(body):
        return True
    lowered = body.lower()
    if "<html" in lowered or "<body" in lowered or "<div" in lowered:
        return len(_visible_text(body)) <= _EMPTY_SHELL_MAX_CHARS
    if _JS_REQUIRED.search(body):
        return len(body.strip()) <= _EMPTY_SHELL_MAX_CHARS * 4
    return not body.strip()
