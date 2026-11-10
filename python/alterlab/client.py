"""AlterLab SDK - Production-ready Python client for the AlterLab Scraping API.

This SDK provides full feature parity with the AlterLab API including:
- Unified endpoint with all scraping modes (auto, html, js, pdf, ocr)
- Automatic polling for async jobs with exponential backoff
- Advanced options (render_js, screenshot, markdown, PDF generation, OCR)
- Cost controls (max_credits, max_tier, prefer_cost/speed, fail_fast, fallback_on_block)
- Structured extraction (schemas, prompts, profiles)
- Cost estimation before scraping
- Usage tracking and credit management
- Batch scraping with webhooks
- Comprehensive error handling with retries

Version: 2.4.5 (Widens httpx range to >=0.25.2,<1.0)
"""

import asyncio
import email.utils
import logging
import math
import os
import random
import re
import time
import warnings
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    TypedDict,
    Union,
    overload,
)
from urllib.parse import quote, urljoin

import httpx

from alterlab import artifacts as _artifacts
from alterlab._failure_backoff import parse_failure_backoff_detail
from alterlab.actions import ScrapeAction, parse_action_results, serialize_actions
from alterlab._namespaces import ParityMixin, SyncNamespace, UnexpectedResponseHook
from alterlab.research import ResearchMixin
from alterlab.resources.sessions import AsyncSessions, SyncSessions

_SDK_VERSION = "2.4.5"

logger = logging.getLogger("alterlab")


_UNSET = object()

# Server-side long-poll window (seconds) the SDK requests via
# ``GET /api/v1/jobs/{id}?wait=N`` after a sync downgrade (#37371). The server
# caps it at 25s; the per-request httpx timeout is widened to cover it.
_DOWNGRADE_LONG_POLL_SECONDS = 20

# Default ceiling (seconds) on the total time one request may spend sleeping
# between retries. A Retry-After that would push past it is not waited out:
# the RateLimitError (carrying ``retry_after``) is raised immediately so the
# caller decides when to come back instead of the call blocking for minutes.
_DEFAULT_MAX_RETRY_WAIT = 60.0

# A server-supplied Retry-After is a floor; up to this fraction is added on
# top so clients that were rejected together do not retry in lockstep.
_RETRY_AFTER_JITTER = 0.2


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date, RFC 9110).

    Returns non-negative seconds, or ``None`` when the header is absent or
    unparseable (an edge/WAF 429 can carry anything).
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def _compute_retry_sleep(
    attempt: int, retry_delay: float, retry_after: Optional[float]
) -> float:
    """Jittered exponential backoff, never shorter than ``retry_after``.

    Without a server hint the delay is "equal jitter" over
    ``retry_delay * 2**attempt``; with one, the server value plus up to
    ``_RETRY_AFTER_JITTER`` of itself, or the backoff if that is longer.
    """
    base = retry_delay * (2**attempt)
    backoff = base * random.uniform(0.5, 1.0)
    if retry_after is None:
        return backoff
    return max(retry_after * random.uniform(1.0, 1.0 + _RETRY_AFTER_JITTER), backoff)


def _ascii_safe_header_value(value: str) -> str:
    """Return ``value`` guaranteed to be a valid US-ASCII HTTP header value.

    HTTP header field values must be US-ASCII (RFC 7230); ``httpx`` (and the
    underlying stdlib ``http.client``) raise ``UnicodeEncodeError`` if handed
    a non-ASCII string directly, crashing the request before it is ever sent
    (#28634). Printable ASCII strings -- the overwhelmingly common case --
    pass through byte-identical to preserve existing behavior; anything else
    is percent-encoded.

    "Anything else" deliberately includes ASCII control characters such as
    CR/LF: a raw newline in a header value also crashes the transport (and
    would smuggle a header break if it did not), so it must be encoded too.
    ``errors="replace"`` keeps unpaired UTF-16 surrogates from raising
    ``UnicodeEncodeError`` -- the very error class this helper exists to
    prevent. Encoding matches the Node SDK's ``asciiSafeHeaderValue`` (RFC
    3986) byte-for-byte for well-formed input, so both SDKs emit identical
    ``X-Agent-*`` headers.
    """
    # Fast path: printable ASCII (including space) is already a valid header
    # value. str.isprintable() is False for control chars (CR, LF, tab, DEL),
    # routing them into the encoder below.
    if value.isascii() and value.isprintable():
        return value
    return quote(value, safe="", encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Response type hints (TypedDicts for IDE/type-checker support)
# ---------------------------------------------------------------------------


# BEGIN GENERATED: output-formats (scripts/generate_output_formats.py; do not edit)
OutputFormat = Literal[
    "text",
    "json",
    "json_v2",
    "html",
    "markdown",
    "rag",
    "content",
    "raw",
    "document",
]
"""Output formats accepted by the ``formats`` option (mirrors the API schema)."""
# END GENERATED: output-formats


class TierEscalationDetail(Dict[str, Any]):
    """Details of a single tier escalation attempt within a scrape request.

    These fields are internal and may not appear in all responses.

    Fields:
        tier: Tier identifier (e.g. "1", "2", "3", "3.5", "4").
        result: Outcome — ``"success"``, ``"failed"``, or ``"skipped"``.
        credits: Credits charged for this tier attempt (microcents).
        duration_ms: Time taken for this tier attempt in milliseconds.
        error: Error message if the tier attempt failed.
    """


class BillingDetails(Dict[str, Any]):
    """Detailed billing breakdown returned in every scrape response.

    Accessed via ``response["billing"]``.

    Fields:
        total_credits: Total credits charged for the request (microcents).
        estimated_credits: Pre-flight likely cost (see ``estimate_cost``) to compare with
            ``total_credits``.
        tier_used: Scraping tier that produced the final result (e.g. "1", "4").
        escalations: List of :class:`TierEscalationDetail` for each tier attempted.
            Internal — only present when ``x-internal`` fields are not filtered.
        savings: Credits saved vs. always using the highest tier. Internal.
        optimization_suggestion: Advisory on how to reduce cost next time. Internal.
        byop_applied: Whether a Bring-Your-Own-Proxy discount was applied.
        byop_discount_percent: Discount percentage applied (e.g. ``98.4``).
        original_cost_microcents: Cost before BYOP discount in microcents.
        final_cost_microcents: Cost after BYOP discount in microcents.
        byos_applied: Whether Bring-Your-Own-Session cookies were injected.
        byos_session_name: Name of the stored session used (e.g. ``"My Amazon Prime"``).
        proxy_bytes: Measured proxy wire bytes this request used.
        included_bytes: Proxy bytes covered by the base price of the tier used.
        billed_extra_mib: Started MiB above the included bytes that were surcharged.
        byte_surcharge_credits: Byte surcharge debited at settlement (same unit as
            ``total_credits``).
    """


# Valid keys and content types for section_filter validation.
_SECTION_FILTER_VALID_KEYS = {
    "min_content_blocks",
    "exclude_content_types",
    "content_only",
}
_SECTION_FILTER_VALID_CONTENT_TYPES = {
    "paragraph",
    "list",
    "table",
    "image",
    "code",
    "blockquote",
    "dl",
    "details",
}


class AdvancedOptions:
    """Advanced scraping options with credit costs.

    Credit Costs:
    - render_js: Forces Tier 4 minimum (browser rendering) — Tier 4 cost applies, no separate add-on charge
    - screenshot: +1 credit (requires render_js)
    - generate_pdf: +2 credits (requires render_js)
    - ocr: +5 credits (refunded if no images found)
    - use_proxy: +1 credit
    - markdown: Free
    - wait_condition: Free
    - remove_cookie_banners: Free
    """

    def __init__(
        self,
        render_js: Union[bool, Literal["auto"]] = False,
        screenshot: bool = False,
        markdown: bool = False,
        generate_pdf: bool = False,
        ocr: bool = False,
        use_proxy: Union[bool, object] = _UNSET,
        use_own_proxy: bool = False,
        use_system_proxy: bool = False,
        proxy_integration_id: Optional[str] = None,
        proxy_country: Optional[str] = None,
        remove_cookie_banners: bool = True,
        wait_condition: str = "networkidle",
        scroll_to_load: bool = False,
        scroll_count: int = 3,
        include_iframes: bool = False,
        flatten_shadow_dom: bool = False,
        block_images: Optional[bool] = None,
        section_filter: Optional[Dict[str, Any]] = None,
        session_headers: Optional[Dict[str, str]] = None,
        sticky_session: Optional[str] = None,
        sticky_session_ttl: Optional[int] = None,
        skip_tls_verification: Optional[bool] = None,
    ):
        """Initialize advanced options.

        Args:
            render_js: Render JavaScript using headless browser (forces Tier 4 minimum — no separate
                add-on charge, Tier 4 cost applies). Set to ``"auto"`` for smart detection: probes
                each page and only renders JS-heavy pages with a browser, using fast HTTP for static
                pages. Saves 30–60% on mixed sites. Note: screenshot and generate_pdf require
                ``render_js=True`` (not ``"auto"``), since they need guaranteed browser rendering.
            screenshot: Capture full-page screenshot (+1 credit, requires render_js=True)
            markdown: Extract content as Markdown (free)
            generate_pdf: Generate PDF of rendered page (+2 credits, requires render_js=True)
            ocr: Extract text from images using OCR (+5 credits)
            use_proxy: Route request through premium proxy (+1 credit). Omit this argument to
                allow platform-driven reactive proxy routing; pass False to request direct routing.
            use_own_proxy: Use your own integrated proxy instead of the system proxy
            use_system_proxy: Override your default proxy integration and use AlterLab's system
                proxy instead
            proxy_integration_id: Specific proxy integration ID to use (requires
                use_own_proxy=True)
            proxy_country: ISO 3166-1 alpha-2 country code for geo-targeted proxy routing
                (e.g., ``"US"``, ``"DE"``, ``"GB"``). The API validates this value against a
                supported-countries allowlist — unsupported codes return HTTP 422. Common
                supported codes include major markets: US, GB, DE, FR, IT, ES, NL, CA, JP,
                SG, AU, BR, IN, and 140+ others. Pass ``None`` to use automatic country
                selection.
            remove_cookie_banners: Remove cookie consent banners from HTML before content
                extraction (free, enabled by default)
            wait_condition: Wait condition for JS rendering (domcontentloaded|networkidle|load)
            scroll_to_load: Scroll page to trigger lazy-loaded content (requires render_js)
            scroll_count: Number of scroll iterations when scroll_to_load is enabled (1-10)
            include_iframes: Inline iframe content into the main document (free, requires render_js).
                Same-origin iframes are read directly; cross-origin iframes are marked but not fetched.
            flatten_shadow_dom: Flatten Shadow DOM roots into regular DOM for extraction (free,
                requires render_js). Web Components with shadow roots become visible in the
                serialized HTML.
            skip_tls_verification: TLS certificate verification. Leave as ``None``
                (recommended): certificates are verified, and if a site's own certificate is
                invalid (expired, self-signed, wrong hostname, incomplete chain) the page is
                still fetched without verification. ``True`` skips verification from the
                start. ``False`` always requires a valid certificate; such sites then fail.
            block_images: Skip image downloads during browser rendering to reduce proxy bandwidth.
                When ``True``, the browser aborts image requests — ``<img>`` src URLs remain in
                the DOM so HTML and text extraction are unaffected, but image bytes are not
                downloaded. When ``False``, all images are downloaded (higher bandwidth, needed
                for visual accuracy). When ``None`` (default), the per-domain playbook setting
                is used. Note: ``screenshot`` and ``generate_pdf`` always download images
                regardless of this setting.
            section_filter: Filter options for json_v2 section tree output. Dict with optional keys:
                - min_content_blocks (int): Minimum content blocks for a section (default 0)
                - exclude_content_types (list[str]): Content types to exclude
                  (paragraph, list, table, image, code, blockquote, dl, details)
                - content_only (bool): Strip headings, keep only content (default False)
            session_headers: Inline auth headers (e.g. {"Authorization": "Bearer token"}).
                Merged with session headers when session_id is also provided.
            sticky_session: Customer-facing sticky-session handle. Two separate ``scrape()``
                calls that pass the same ``sticky_session`` value are pinned to the SAME exit
                IP and automatically share the cookies captured on the first call (see
                ``captured_cookies`` in the response), for the handle's TTL. Enables stateful
                multi-request flows — e.g. request 1 loads a page, request 2 fetches the
                captcha/image that appeared using request 1's IP + cookie jar. Requires a paid
                plan (growth tier or above; the API returns HTTP 403
                ``STICKY_SESSION_REQUIRES_PLAN`` otherwise). Must be 1–128 characters of
                letters, digits, ``-`` or ``_`` only. Pass ``None`` (default) to disable.
            sticky_session_ttl: Sticky-session lifetime in seconds (300–7200, default 1800
                applied server-side). Captured cookies bound to ``sticky_session`` are held
                for this window, after which the handle resolves to a fresh IP/jar. Ignored
                unless ``sticky_session`` is set.

        Raises:
            ValueError: If render_js is not a bool or the string ``"auto"``
            ValueError: If screenshot or generate_pdf is True but render_js is not True
            ValueError: If scroll_to_load is True but render_js is falsy
            ValueError: If include_iframes or flatten_shadow_dom is True but render_js is falsy
            ValueError: If scroll_count is not between 1 and 10
            ValueError: If section_filter contains unknown keys or invalid value types
            ValueError: If sticky_session is not 1-128 chars of [A-Za-z0-9_-]
            ValueError: If sticky_session_ttl is set outside the 300-7200 range
        """
        if render_js not in (True, False, "auto"):
            raise ValueError('render_js must be True, False, or "auto"')
        if screenshot and render_js is not True:
            raise ValueError(
                "screenshot requires render_js=True "
                '(render_js="auto" is not sufficient — screenshot needs guaranteed browser rendering)'
            )
        if generate_pdf and render_js is not True:
            raise ValueError(
                "generate_pdf requires render_js=True "
                '(render_js="auto" is not sufficient — PDF generation needs guaranteed browser rendering)'
            )
        if scroll_to_load and not render_js:
            raise ValueError(
                "scroll_to_load requires render_js=True or render_js='auto'"
            )
        if include_iframes and not render_js:
            raise ValueError(
                "include_iframes requires render_js=True or render_js='auto'"
            )
        if flatten_shadow_dom and not render_js:
            raise ValueError(
                "flatten_shadow_dom requires render_js=True or render_js='auto'"
            )

        valid_conditions = ["domcontentloaded", "networkidle", "load"]
        if wait_condition not in valid_conditions:
            raise ValueError(f"wait_condition must be one of {valid_conditions}")

        if not 1 <= scroll_count <= 10:
            raise ValueError("scroll_count must be between 1 and 10")

        # Mirror the API's sticky_session charset validator (#29555). The handle is
        # hashed with the caller's user_id into a proxy-username segment and used as a
        # Redis key component, so it must be restricted to [A-Za-z0-9_-] to prevent
        # injection. Normalizing (strip, empty -> None) matches the server behavior so a
        # blank handle is a no-op rather than an opaque 4xx.
        if sticky_session is not None:
            sticky_session = sticky_session.strip()
            if not sticky_session:
                sticky_session = None
            elif not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sticky_session):
                raise ValueError(
                    "sticky_session must be 1-128 characters of letters, digits, '-' or '_'"
                )
        if sticky_session_ttl is not None and not 300 <= sticky_session_ttl <= 7200:
            raise ValueError("sticky_session_ttl must be between 300 and 7200 seconds")

        self.render_js = render_js
        self.screenshot = screenshot
        self.markdown = markdown
        self.generate_pdf = generate_pdf
        self.ocr = ocr
        # Keep the public attribute boolean-compatible while retaining whether the
        # caller supplied this omission-sensitive option for wire serialization.
        self._use_proxy_supplied = use_proxy is not _UNSET
        self._use_proxy = False if use_proxy is _UNSET else use_proxy
        self.use_own_proxy = use_own_proxy
        self.use_system_proxy = use_system_proxy
        self.proxy_integration_id = proxy_integration_id
        self.proxy_country = proxy_country
        self.remove_cookie_banners = remove_cookie_banners
        self.wait_condition = wait_condition
        self.scroll_to_load = scroll_to_load
        self.scroll_count = scroll_count
        self.include_iframes = include_iframes
        self.flatten_shadow_dom = flatten_shadow_dom
        self.block_images = block_images
        self.session_headers = session_headers
        self.sticky_session = sticky_session
        self.sticky_session_ttl = sticky_session_ttl
        self.skip_tls_verification = skip_tls_verification

        if section_filter is not None:
            self._validate_section_filter(section_filter)
        self.section_filter = section_filter

    @property
    def use_proxy(self) -> bool:
        """Whether premium proxy routing was requested."""
        return self._use_proxy

    @use_proxy.setter
    def use_proxy(self, value: bool) -> None:
        # Public post-construction mutation is an explicit caller decision and
        # must not be mistaken for the constructor's omitted default.
        self._use_proxy = value
        self._use_proxy_supplied = True

    @staticmethod
    def _validate_section_filter(sf: Dict[str, Any]) -> None:
        """Validate section_filter keys and value types.

        Raises:
            ValueError: If any key is not in the allowed set, or if value
                types do not match the expected schema.
        """
        if not isinstance(sf, dict):
            raise ValueError("section_filter must be a dict")

        unknown_keys = set(sf.keys()) - _SECTION_FILTER_VALID_KEYS
        if unknown_keys:
            raise ValueError(
                f"section_filter contains unknown keys: {sorted(unknown_keys)}. "
                f"Allowed keys: {sorted(_SECTION_FILTER_VALID_KEYS)}"
            )

        if "min_content_blocks" in sf:
            val = sf["min_content_blocks"]
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise ValueError(
                    "section_filter['min_content_blocks'] must be a non-negative integer"
                )

        if "exclude_content_types" in sf:
            val = sf["exclude_content_types"]
            if not isinstance(val, (list, tuple)):
                raise ValueError(
                    "section_filter['exclude_content_types'] must be a list of strings"
                )
            invalid = set(val) - _SECTION_FILTER_VALID_CONTENT_TYPES
            if invalid:
                raise ValueError(
                    f"section_filter['exclude_content_types'] contains unknown types: "
                    f"{sorted(invalid)}. "
                    f"Allowed: {sorted(_SECTION_FILTER_VALID_CONTENT_TYPES)}"
                )

        if "content_only" in sf:
            val = sf["content_only"]
            if not isinstance(val, bool):
                raise ValueError("section_filter['content_only'] must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API request."""
        result: Dict[str, Any] = {
            "render_js": self.render_js,
            "screenshot": self.screenshot,
            "markdown": self.markdown,
            "generate_pdf": self.generate_pdf,
            "ocr": self.ocr,
            "use_own_proxy": self.use_own_proxy,
            "use_system_proxy": self.use_system_proxy,
            "remove_cookie_banners": self.remove_cookie_banners,
            "wait_condition": self.wait_condition,
            "scroll_to_load": self.scroll_to_load,
            "scroll_count": self.scroll_count,
            "include_iframes": self.include_iframes,
            "flatten_shadow_dom": self.flatten_shadow_dom,
        }
        if self._use_proxy_supplied:
            result["use_proxy"] = self.use_proxy
        if self.scroll_to_load:
            result["scroll_to_load"] = True
            result["scroll_count"] = self.scroll_count
        if self.block_images is not None:
            result["block_images"] = self.block_images
        if self.skip_tls_verification is not None:
            result["skip_tls_verification"] = self.skip_tls_verification
        if self.section_filter is not None:
            result["section_filter"] = self.section_filter
        if self.session_headers is not None:
            result["session_headers"] = self.session_headers
        if self.proxy_integration_id is not None:
            result["proxy_integration_id"] = self.proxy_integration_id
        if self.proxy_country is not None:
            result["proxy_country"] = self.proxy_country
        if self.sticky_session is not None:
            result["sticky_session"] = self.sticky_session
        if self.sticky_session_ttl is not None:
            result["sticky_session_ttl"] = self.sticky_session_ttl
        return result

    def calculate_credits(self) -> int:
        """Calculate additional credits for advanced options.

        Note: render_js="auto" does not add upfront credits — actual cost depends on
        per-page decision (browser vs. HTTP). Treat as 0 for estimation purposes.
        """
        credits = 0
        if self.render_js is True:
            credits += 3
        # render_js="auto" doesn't add credits upfront — actual cost depends on per-page decision
        if self.screenshot:
            credits += 1
        if self.generate_pdf:
            credits += 2
        if self.ocr:
            credits += 5
        if self.use_proxy:
            credits += 1
        return credits


class CostControls:
    """Cost control parameters for scraping requests.

    Provides fine-grained control over credit spending and tier escalation.
    """

    def __init__(
        self,
        max_credits: Optional[float] = None,
        max_tier: Optional[str] = None,
        force_tier: Optional[str] = None,
        prefer_cost: bool = False,
        prefer_speed: bool = False,
        fail_fast: bool = False,
        time_budget: Optional[float] = None,
        fallback_on_block: bool = False,
    ):
        """Initialize cost controls.

        Args:
            max_credits: Maximum credits to spend on this request
            max_tier: Maximum tier to escalate to (1, 2, 3, 3.5, 4)
            force_tier: Force a specific tier, skipping escalation entirely
                (1=curl, 2=http, 3=dynamic, 3.5=lightjs, 4=browser).
                Must be <= max_tier when both are provided.
            prefer_cost: Optimize for cost (try cheaper tiers first)
            prefer_speed: Optimize for speed (skip to reliable tier)
            fail_fast: Return error instead of escalating to expensive tiers
            time_budget: Total wall-clock budget in seconds for the entire tier
                escalation sequence (5–300). Escalation to the next tier is
                skipped if the remaining budget is insufficient for a meaningful
                attempt (T3 needs ≥5s, T4 needs ≥10s). When the budget is
                exhausted the response includes ``time_budget_expired=true``.
                Default: no limit.
            fallback_on_block: Opt-in. Applies only when the request forces
                browser rendering (``render_js=True`` or ``force_tier="4"``).
                If the browser attempt ends in a verification challenge or a
                timeout, the platform retries once at the dynamic tier (T3/T3.5)
                and bills the tier that returned the page (``billing.tier_used``).
                Ignored when actions, screenshot, generate_pdf or ocr are
                requested. Default: False.

        Raises:
            ValueError: If max_tier or force_tier is not a valid tier value
            ValueError: If force_tier exceeds max_tier
            ValueError: If time_budget is outside the range [5, 300]
        """
        valid_tiers = ["1", "2", "3", "3.5", "4"]
        if max_tier and max_tier not in valid_tiers:
            raise ValueError(f"max_tier must be one of {valid_tiers}")

        if force_tier and force_tier not in valid_tiers:
            raise ValueError(f"force_tier must be one of {valid_tiers}")

        if force_tier and max_tier and float(force_tier) > float(max_tier):
            raise ValueError(
                f"force_tier ({force_tier}) cannot exceed max_tier ({max_tier})"
            )

        if max_credits and max_credits <= 0:
            raise ValueError("max_credits must be greater than 0")

        if time_budget is not None and not (5 <= time_budget <= 300):
            raise ValueError("time_budget must be between 5 and 300 seconds")

        self.max_credits = max_credits
        self.max_tier = max_tier
        self.force_tier = force_tier
        self.prefer_cost = prefer_cost
        self.prefer_speed = prefer_speed
        self.fail_fast = fail_fast
        self.time_budget = time_budget
        self.fallback_on_block = fallback_on_block

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API request."""
        result = {
            "prefer_cost": self.prefer_cost,
            "prefer_speed": self.prefer_speed,
            "fail_fast": self.fail_fast,
        }
        if self.max_credits is not None:
            result["max_credits"] = self.max_credits
        if self.max_tier is not None:
            result["max_tier"] = self.max_tier
        if self.force_tier is not None:
            result["force_tier"] = self.force_tier
        if self.time_budget is not None:
            result["time_budget"] = self.time_budget
        if self.fallback_on_block:
            result["fallback_on_block"] = True
        return result


class AlterLabError(Exception):
    """Base exception for AlterLab SDK errors."""

    pass


class ForcedRenderHint(TypedDict):
    """Retry guidance attached to some failed jobs as ``error.hint``.

    Present when a request forced browser rendering (``render_js=True`` or
    ``cost_controls.force_tier="4"``) and the page returned a verification
    screen or did not finish loading in time. ``code`` is ``"render_js_auto"``:
    retrying with ``render_js="auto"`` lets the platform start at the lowest
    tier that returns the page.
    """

    code: str
    reason: str
    message: str


def _coerce_hint(value: Any) -> Optional[ForcedRenderHint]:
    """Return a ForcedRenderHint from ``value`` when it is well-formed, else None."""
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    message = value.get("message")
    if not isinstance(code, str) or not isinstance(message, str):
        return None
    reason = value.get("reason")
    return ForcedRenderHint(
        code=code,
        reason=reason if isinstance(reason, str) else "",
        message=message,
    )


def _hint_from_response(
    response: Optional[httpx.Response],
) -> Optional[ForcedRenderHint]:
    """Read ``error.hint`` from a failed sync scrape response body."""
    if response is None:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    return _coerce_hint(error.get("hint"))


class AlterLabAPIError(AlterLabError):
    """API error with status code and detail.

    :attr:`hint` holds the :class:`ForcedRenderHint` from the response's
    ``error.hint`` when the API sent one, otherwise ``None``.
    """

    hint: Optional[ForcedRenderHint] = None

    def __init__(
        self, status_code: int, detail: str, response: Optional[httpx.Response] = None
    ):
        """Initialize API error.

        Args:
            status_code: HTTP status code
            detail: Error detail message
            response: Optional httpx Response object for inspection
        """
        self.status_code = status_code
        self.detail = detail
        self.response = response
        self.hint = _hint_from_response(response)
        super().__init__(f"API Error {status_code}: {detail}")


class AlterLabTimeoutError(AlterLabError):
    """SDK-side poll timeout for async job polling.

    Raised by :meth:`AlterLab.wait_for_job` when the SDK's ``poll_timeout``
    elapses before the job reaches a terminal state.  This is distinct from
    job TTL expiry — the job may still be running on the server.

    To distinguish from a job that has already expired (server-side, 1-hour
    TTL), catch :class:`JobExpiredError` separately before this exception.
    """

    pass


class JobTimeoutError(AlterLabTimeoutError):
    """Poll timeout for a specific job (#40284).

    Subclass of :class:`AlterLabTimeoutError`, so existing handlers keep
    working. The job may still be running server-side and credits may still be
    held: resume with ``get_job_status(e.job_id)`` or ``e.poll_url``.
    """

    def __init__(self, job_id: str, poll_timeout: float):
        self.job_id = job_id
        self.poll_url = f"/api/v1/jobs/{job_id}"
        super().__init__(f"Job {job_id} did not complete within {poll_timeout} seconds")


class ScrapeAcceptedResponse(TypedDict, total=False):
    """202 envelope returned by ``scrape(sync=False)`` (async job accepted)."""

    job_id: str
    status: str
    poll_url: str
    sync_downgraded: bool
    reason: str
    credits_status: str


class JobExpiredError(AlterLabAPIError):
    """Raised when polling a job that has expired on the server.

    Job results are stored in Redis with a 1-hour TTL.  After that window the
    server returns HTTP 404, which :meth:`AlterLab.wait_for_job` and
    :meth:`AlterLab.get_job_status` surface as this exception instead of the
    generic :class:`AlterLabAPIError`.

    Callers should **not** retry with the same ``job_id`` — the result is gone.
    Submit a new request with :meth:`AlterLab.scrape`.

    Example::

        try:
            result = await client.wait_for_job(job_id)
        except JobExpiredError:
            # Job TTL exceeded — start a new one
            result = await client.scrape(url)
        except AlterLabTimeoutError:
            # SDK poll_timeout exceeded — job may still be running
            ...
    """

    pass


class AlterLabValidationError(AlterLabError):
    """Validation error for request parameters."""

    pass


class AuthenticationError(AlterLabAPIError):
    """Raised when the API returns HTTP 401 (invalid or missing API key).

    This is a subclass of :class:`AlterLabAPIError`, so existing
    ``except AlterLabAPIError`` handlers still catch it.

    Example::

        try:
            result = await client.scrape("https://example.com")
        except AuthenticationError:
            print("Check your API key at https://alterlab.io/dashboard/keys")
    """

    pass


class InsufficientFundsError(AlterLabAPIError):
    """Raised when the API returns HTTP 402 (insufficient balance).

    Includes a :attr:`billing_url` attribute pointing to the billing
    dashboard where the user can add funds. Insufficient-balance responses also
    carry :attr:`topup_url` (a signed, short-lived link to the quick top-up
    confirm banner; it never charges) and, while the account's welcome offer is
    active, :attr:`welcome_offer` (``{"expires_at", "match_pct"}``). Both are
    ``None`` when the server did not send them.

    This is a subclass of :class:`AlterLabAPIError`, so existing
    ``except AlterLabAPIError`` handlers still catch it.

    Example::

        try:
            result = await client.scrape("https://example.com")
        except InsufficientFundsError as e:
            print(f"Add funds at: {e.topup_url or e.billing_url}")
    """

    billing_url: str = "https://alterlab.io/dashboard/billing"
    topup_url: Optional[str] = None
    welcome_offer: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        status_code: int,
        detail: str,
        response: Optional[httpx.Response] = None,
    ):
        super().__init__(status_code, detail, response)
        self.billing_url = "https://alterlab.io/dashboard/billing"
        self.topup_url = None
        self.welcome_offer = None
        try:
            body = response.json() if response is not None else None
        except Exception:
            body = None
        # The fields sit under ``detail`` (API), top level (Firecrawl-compat)
        # or under ``error`` (sync scrape rejection) depending on the route.
        layers = [body] if isinstance(body, dict) else []
        for key in ("detail", "error"):
            if layers and isinstance(layers[0].get(key), dict):
                layers.append(layers[0][key])
        for layer in layers:
            if self.topup_url is None and isinstance(layer.get("topup_url"), str):
                self.topup_url = layer["topup_url"]
            if self.welcome_offer is None and isinstance(
                layer.get("welcome_offer"), dict
            ):
                self.welcome_offer = layer["welcome_offer"]


class RateLimitError(AlterLabAPIError):
    """Raised when the API returns HTTP 429 and the SDK stops retrying.

    That happens when all retry attempts are exhausted, or earlier when
    waiting out the next ``Retry-After`` would exceed the client's
    ``max_retry_wait``.

    Includes a :attr:`retry_after` attribute with the number of seconds
    the server suggested waiting (from the ``Retry-After`` header, falling
    back to ``detail.retry_after_seconds`` in the body), or ``None`` if
    neither was present.

    The fields of the canonical 429 body (``{"error", "message", "detail":
    {"scope", "limit", "account_tier", "retry_after_seconds"}, "docs_url"}``)
    and the ``RateLimit-*`` headers are surfaced as attributes. They are
    ``None`` for a 429 without that body, e.g. one served by the edge
    (``error code: 1015``) rather than the API.

    :attr:`consecutive_failures`, :attr:`outcome_class` and
    :attr:`failure_code` are set only for the repeat-failure back-off 429
    (``error_code == "repeat_failure_backoff"``): an uncharged 429 returned
    when the same request failed the same way several times in a row. Its
    retry guidance is in :attr:`hint` (``hint["code"] ==
    "repeat_failure_backoff"``): retry after ``retry_after``, retry with
    different request options, or pass ``force_refresh=True``.

    This is a subclass of :class:`AlterLabAPIError`, so existing
    ``except AlterLabAPIError`` handlers still catch it.

    .. note::

        The SDK automatically retries 429 responses with jittered
        exponential backoff that honours ``Retry-After``.

    Example::

        try:
            result = await client.scrape("https://example.com")
        except RateLimitError as e:
            if e.retry_after:
                print(f"Rate limited ({e.scope}). Retry after {e.retry_after}s")
    """

    retry_after: Optional[float] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    scope: Optional[str] = None
    limit: Optional[int] = None
    account_tier: Optional[str] = None
    docs_url: Optional[str] = None
    rate_limit_limit: Optional[str] = None
    rate_limit_remaining: Optional[str] = None
    rate_limit_reset: Optional[str] = None
    consecutive_failures: Optional[int] = None
    outcome_class: Optional[str] = None
    failure_code: Optional[str] = None

    def __init__(
        self,
        status_code: int,
        detail: str,
        response: Optional[httpx.Response] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(status_code, detail, response)
        self.retry_after = retry_after
        if response is None:
            return

        headers = response.headers
        self.rate_limit_limit = headers.get("RateLimit-Limit") or headers.get(
            "X-RateLimit-Limit"
        )
        self.rate_limit_remaining = headers.get("RateLimit-Remaining")
        self.rate_limit_reset = headers.get("RateLimit-Reset")
        self.scope = headers.get("X-RateLimit-Scope")

        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return
        if isinstance(body.get("error"), str):
            self.error_code = body["error"]
        if isinstance(body.get("message"), str):
            self.message = body["message"]
        if isinstance(body.get("docs_url"), str):
            self.docs_url = body["docs_url"]
        body_detail = body.get("detail")
        if isinstance(body_detail, dict):
            if isinstance(body_detail.get("scope"), str):
                self.scope = body_detail["scope"]
            if isinstance(body_detail.get("limit"), int):
                self.limit = body_detail["limit"]
            if isinstance(body_detail.get("account_tier"), str):
                self.account_tier = body_detail["account_tier"]
            body_retry = body_detail.get("retry_after_seconds")
            if self.retry_after is None and isinstance(body_retry, (int, float)):
                self.retry_after = float(body_retry)
            (
                self.consecutive_failures,
                self.outcome_class,
                self.failure_code,
            ) = parse_failure_backoff_detail(body_detail)
            if self.hint is None:
                self.hint = _coerce_hint(body_detail.get("hint"))


class JobFailedError(AlterLabAPIError):
    """Raised when a polled job reaches a terminal failure state.

    Covers the server's ``failed``, ``rejected``, and ``cancelled`` terminal
    statuses (see ``JobStatus`` in ``services/api/app/models/job.py``) — all
    three mean the job will never produce a result, distinct from
    :class:`AlterLabTimeoutError` (SDK gave up waiting; job may still be
    running) and :class:`JobExpiredError` (result TTL elapsed).

    This is a subclass of :class:`AlterLabAPIError` (matching
    :class:`JobExpiredError`, :class:`AuthenticationError`,
    :class:`InsufficientFundsError`, and :class:`RateLimitError`), so
    existing ``except AlterLabAPIError`` handlers still catch it — the
    previous implementation always raised a plain ``AlterLabAPIError`` for a
    failed job, and callers written against that contract must not start
    silently missing this case.
    """

    def __init__(self, job_id: str, status: str, detail: str):
        self.job_id = job_id
        self.status = status
        self.detail = detail
        # The job's ``error`` object may carry a retry hint (``error.hint``).
        self.hint = (
            _coerce_hint(detail.get("hint")) if isinstance(detail, dict) else None
        )
        # Deliberately bypass AlterLabAPIError.__init__'s message formatting
        # (`f"API Error {status_code}: {detail}"`) in favor of the more
        # specific job_id/status wording below, while still setting the
        # status_code/detail/response attributes it establishes so
        # attribute-based handling of a caught AlterLabAPIError keeps working.
        self.status_code = 500
        self.response = None
        Exception.__init__(self, f"Job {job_id} ended with status '{status}': {detail}")


def get_error_hint(error: Any) -> Optional[ForcedRenderHint]:
    """Return the retry hint carried by a failed request, job or crawl page.

    Accepts an :class:`AlterLabAPIError` (including :class:`JobFailedError`)
    or a raw error object such as a crawl page's ``error`` dict. Returns
    ``None`` when there is no well-formed hint.

    Example::

        try:
            result = await client.scrape(url, advanced=AdvancedOptions(render_js=True))
        except AlterLabAPIError as e:
            hint = get_error_hint(e)
            if hint:
                print(hint["message"])
    """
    if isinstance(error, AlterLabAPIError):
        return getattr(error, "hint", None)
    if isinstance(error, dict):
        return _coerce_hint(error.get("hint"))
    return None


# Canonical job-status vocabulary, mirrored from ``JobStatus`` in
# ``services/api/app/models/job.py`` (the server's single source of truth,
# enforced by a DB CHECK constraint since migration 0263). ``succeeded`` is
# the value current worker code writes on completion; ``completed`` is kept
# only for backward compatibility with historical rows (migration 0021
# normalized all `completed` rows to `succeeded` and no current write path
# produces it). Reused by both ``wait_for_job`` here and by any future
# job-status consumer so the two never drift independently again (#31823).
_JOB_STATUS_SUCCEEDED = frozenset({"succeeded", "completed"})
_JOB_STATUS_FAILED = frozenset({"failed", "rejected", "cancelled"})
_JOB_STATUS_IN_PROGRESS = frozenset({"pending", "queued", "running", "retrying"})


class AlterLab(ResearchMixin, ParityMixin):
    """AlterLab API client with full feature support.

    This client provides:
    - Unified scraping endpoint with all modes (auto, html, js, pdf, ocr)
    - Automatic polling for async jobs with configurable backoff
    - Advanced features (render_js, screenshot, markdown, PDF, OCR)
    - Cost controls and estimation
    - Structured extraction with schemas, prompts, and profiles
    - Batch scraping with webhooks
    - Comprehensive error handling with automatic retries
    - Usage tracking and credit management

    Example:
        async with AlterLab(api_key="sk_test_...") as client:
            # Simple scraping
            result = await client.scrape("https://example.com")

            # Advanced scraping with JS rendering and screenshot
            result = await client.scrape(
                "https://example.com",
                mode="js",
                advanced=AdvancedOptions(render_js=True, screenshot=True)
            )

            # Estimate cost before scraping
            estimate = await client.estimate_cost("https://example.com")
            print(f"Estimated credits: {estimate['estimated_credits']}")

        # Or, with ALTERLAB_API_KEY set in the environment:
        async with AlterLab() as client:
            result = await client.scrape("https://example.com")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.alterlab.io",
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_retry_wait: Optional[float] = _DEFAULT_MAX_RETRY_WAIT,
        on_unexpected_response: Optional[UnexpectedResponseHook] = None,
    ):
        """Initialize AlterLab client.

        Args:
            api_key: Your API key (get from https://dashboard.alterlab.io). If
                not provided, reads from the ``ALTERLAB_API_KEY`` environment
                variable.
            base_url: API base URL (default: https://api.alterlab.io)
            timeout: Default request timeout in seconds
            max_retries: Maximum number of retries for transient failures
            retry_delay: Initial delay between retries in seconds (jittered
                exponential backoff; a longer ``Retry-After`` takes precedence)
            max_retry_wait: Maximum total seconds one request may spend
                sleeping between retries (default 60). When the next wait
                would exceed it the last error (e.g. :class:`RateLimitError`
                with ``retry_after``) is raised instead. ``None`` disables
                the cap.
            on_unexpected_response: Optional callback invoked with a small dict
                when a parity method (``support``, ``jobs``, ``monitors``, ...)
                gets a non-JSON response. It only notifies you; the SDK never
                files feedback or tickets by itself.

        Raises:
            ValueError: If api_key is not provided and ALTERLAB_API_KEY is not set
        """
        resolved_api_key = api_key or os.environ.get("ALTERLAB_API_KEY", "")
        if not resolved_api_key or not resolved_api_key.strip():
            raise ValueError(
                "AlterLab API key is required. Pass api_key= or set "
                "ALTERLAB_API_KEY environment variable."
            )

        self.api_key = resolved_api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        if max_retry_wait is not None and max_retry_wait < 0:
            raise ValueError("max_retry_wait must be >= 0 or None")
        self.max_retry_wait = max_retry_wait

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": resolved_api_key,
                "User-Agent": f"AlterLab-Python-SDK/{_SDK_VERSION}",
                "X-AlterLab-Source": f"python-sdk/{_SDK_VERSION}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

        # Resource namespaces
        self.sessions = AsyncSessions(self)
        self.on_unexpected_response = on_unexpected_response
        self._init_parity()

    def _retry_wait_allowed(self, waited: float, sleep_time: float) -> bool:
        """Whether sleeping ``sleep_time`` more stays within ``max_retry_wait``."""
        if self.max_retry_wait is None:
            return True
        return waited + sleep_time <= self.max_retry_wait

    async def _request_with_retry(
        self, method: str, path: str, **kwargs
    ) -> httpx.Response:
        """Make HTTP request with retry logic for transient failures.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path
            **kwargs: Additional arguments for httpx request

        Returns:
            httpx.Response object

        Raises:
            AlterLabAPIError: On API errors
            AlterLabError: On network errors after all retries
        """
        last_error = None
        waited = 0.0

        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(method, path, **kwargs)

                # Handle error responses
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        detail = error_data.get("detail", response.text)
                        # Canonical error envelopes ({error, message, detail:
                        # {...}, docs_url} — e.g. every 429 since #34574) carry
                        # the human-readable text in top-level ``message`` and
                        # a structured ``detail`` object. Keep ``detail`` a
                        # str; the structured fields are parsed by the typed
                        # errors (see RateLimitError) from ``response``.
                        message = error_data.get("message")
                        if not isinstance(detail, str) and isinstance(message, str):
                            detail = message
                    except Exception:
                        detail = response.text

                    # Don't retry client errors (4xx except 429)
                    if (
                        400 <= response.status_code < 500
                        and response.status_code != 429
                    ):
                        logger.debug(
                            "Non-retriable client error %d on %s %s: %s",
                            response.status_code,
                            method,
                            path,
                            detail,
                        )
                        if response.status_code == 401:
                            raise AuthenticationError(
                                response.status_code, detail, response
                            )
                        if response.status_code == 402:
                            raise InsufficientFundsError(
                                response.status_code, detail, response
                            )
                        raise AlterLabAPIError(response.status_code, detail, response)

                    # Retry server errors (5xx) and rate limits (429)
                    remaining_attempts = self.max_retries - attempt - 1
                    retry_after = _parse_retry_after(
                        response.headers.get("Retry-After")
                    )

                    if response.status_code == 429:
                        last_error = RateLimitError(
                            response.status_code,
                            detail,
                            response,
                            retry_after=retry_after,
                        )
                        retry_after = last_error.retry_after
                    else:
                        last_error = AlterLabAPIError(
                            response.status_code, detail, response
                        )

                    if remaining_attempts <= 0:
                        break

                    sleep_time = _compute_retry_sleep(
                        attempt, self.retry_delay, retry_after
                    )
                    if not self._retry_wait_allowed(waited, sleep_time):
                        logger.warning(
                            "Retriable error %d on %s %s: next retry in %.1fs "
                            "would exceed max_retry_wait=%.1fs (already waited "
                            "%.1fs). Not retrying. Detail: %s",
                            response.status_code,
                            method,
                            path,
                            sleep_time,
                            self.max_retry_wait,
                            waited,
                            detail,
                        )
                        break

                    logger.warning(
                        "Retriable error %d on %s %s (attempt %d/%d). "
                        "Retrying in %.1fs. %d attempts remaining. Detail: %s",
                        response.status_code,
                        method,
                        path,
                        attempt + 1,
                        self.max_retries,
                        sleep_time,
                        remaining_attempts,
                        detail,
                    )
                    waited += sleep_time
                    await asyncio.sleep(sleep_time)
                    continue

                return response

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = AlterLabError(f"Network error: {str(e)}")
                remaining_attempts = self.max_retries - attempt - 1

                sleep_time = _compute_retry_sleep(attempt, self.retry_delay, None)
                if attempt < self.max_retries - 1 and self._retry_wait_allowed(
                    waited, sleep_time
                ):
                    logger.warning(
                        "Network error on %s %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs. %d attempts remaining.",
                        method,
                        path,
                        attempt + 1,
                        self.max_retries,
                        str(e),
                        sleep_time,
                        remaining_attempts,
                    )
                    waited += sleep_time
                    await asyncio.sleep(sleep_time)
                else:
                    logger.error(
                        "Network error on %s %s (attempt %d/%d): %s. "
                        "No retries remaining.",
                        method,
                        path,
                        attempt + 1,
                        self.max_retries,
                        str(e),
                    )
                    break
                continue

        # Retries exhausted (attempts or max_retry_wait budget)
        logger.error(
            "Giving up on %s %s after %.1fs of retry waits (max_retries=%d). "
            "Last error: %s",
            method,
            path,
            waited,
            self.max_retries,
            last_error,
        )
        raise last_error or AlterLabError("Request failed after retries")

    @overload
    async def scrape(
        self, url: str, *args: Any, sync: Literal[False], **kwargs: Any
    ) -> ScrapeAcceptedResponse: ...

    @overload
    async def scrape(self, url: str, *args: Any, **kwargs: Any) -> Dict[str, Any]: ...

    async def scrape(
        self,
        url: str,
        mode: Literal["auto", "html", "js", "pdf", "ocr"] = "auto",
        sync: bool = True,
        advanced: Optional[AdvancedOptions] = None,
        cost_controls: Optional[CostControls] = None,
        force_refresh: bool = False,
        include_raw_html: bool = False,
        timeout: Optional[int] = None,
        formats: Optional[List[OutputFormat]] = None,
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_prompt: Optional[str] = None,
        extraction_profile: Optional[
            Literal[
                "auto",
                "product",
                "article",
                "job_posting",
                "faq",
                "recipe",
                "event",
                "ecommerce_homepage",
                "directory_listing",
            ]
        ] = None,
        evidence: bool = False,
        promote_schema_org: bool = True,
        wait_for: Optional[str] = None,
        screenshot: bool = False,
        wait_until: str = "networkidle",
        pdf_format: str = "markdown",
        ocr_language: str = "eng",
        session_id: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        actions: Optional[Sequence[Union[ScrapeAction, Dict[str, Any]]]] = None,
        actions_on_error: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        agent_intent: Optional[str] = None,
        agent_context: Optional[str] = None,
        agent_feedback: Optional[str] = None,
        location: Optional[Dict[str, str]] = None,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET",
        body: Optional[str] = None,
        content_type: Optional[
            Literal[
                "application/json",
                "application/x-www-form-urlencoded",
                "text/plain",
                "application/graphql",
            ]
        ] = None,
        cache: bool = False,
        max_age: Optional[int] = None,
        cache_ttl: Optional[int] = None,
        webhook_url: Optional[str] = None,
        max_response_bytes: Optional[int] = None,
        template: Optional[str] = None,
        poll_interval: float = 1.0,
        poll_timeout: float = 300.0,
        poll_backoff_multiplier: float = 1.5,
        poll_max_interval: float = 10.0,
        sync_policy: Literal["auto", "wait_until_deadline"] = "auto",
        response: Optional[Literal["full", "minimal"]] = None,
        extraction_selectors: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Scrape a URL using the unified AlterLab API endpoint.

        This is the main method for scraping content. It supports all scraping modes
        and automatically handles async job polling when needed.

        Args:
            url: URL to scrape
            mode: Scraping mode (auto, html, js, pdf, ocr)
            sync: Return synchronous response when possible (default: True).
                  Set to False to always use async worker queue.
            sync_policy: Sync wait policy. ``"auto"`` preserves the server's normal
                  early handoff for predicted higher-tier jobs; ``"wait_until_deadline"``
                  waits for terminal completion up to the server's 85-second safe sync
                  deadline. Requires ``sync=True``.
            response: Response shape. ``"minimal"`` returns only content, status, url,
                cost and warnings; ``"full"`` keeps the complete payload. ``None``
                (default) lets the server choose (minimal for MCP/agent/keyless keys).
            advanced: Advanced scraping options (AdvancedOptions object)
            cost_controls: Cost control parameters (CostControls object)
            force_refresh: Bypass cache and fetch fresh content
            include_raw_html: Include raw HTML in response
            timeout: Request timeout in seconds (overrides default)
            formats: Output formats for content transformation (e.g., ["html", "markdown",
                "content"]). Use ``"content"`` for a deterministic AI/KB extraction mode
                that returns ``body_markdown``, ``content_hash``, ``images``, and ``links``
                in ``result["content"]["content"]`` — suitable for change detection and
                knowledge-base ingestion. Use with :class:`~alterlab.types.ContentResult`
                for typed access.
            extraction_schema: JSON schema dict for structured extraction. The API extracts
                fields matching this schema from the scraped page and returns them in
                ``result["extraction_result"]``. Example::

                    {
                        "hero_banners": [{"image_url": "string"}],
                        "promotions": [{"description": "string", "promo_code": "string | null"}],
                    }
            extraction_prompt: Natural language instructions for extraction
            extraction_selectors: Deterministic ``{field: selector}`` map (1-100
                fields), no LLM or BYOK key needed. Each selector has exactly one of
                ``css`` / ``xpath`` plus optional ``attr`` and ``multiple``. Example::

                    {"price": {"css": ".price", "attr": "content"},
                     "links": {"xpath": "//a", "attr": "href", "multiple": True}}
            extraction_profile: Pre-defined extraction profile (auto, product, article, etc.)
            evidence: Include provenance/evidence for extracted fields
            promote_schema_org: Use Schema.org as primary structure
            wait_for: CSS selector to wait for (JS mode)
            screenshot: Capture screenshot (JS mode, requires advanced.render_js=True)
            wait_until: Wait condition (domcontentloaded|networkidle|load)
            pdf_format: PDF output format (text|markdown)
            ocr_language: OCR language code (e.g., "eng", "fra", "deu")
            session_id: UUID of a stored session integration for authenticated scraping.
                Mutually exclusive with ``cookies``.
            cookies: Inline cookie dict for one-off authenticated scraping (not stored).
                Mutually exclusive with ``session_id``.
            actions: Browser automation sequence to execute after page load (max 20 actions).
                Requires ``advanced.render_js=True``. Each item is a typed action built
                with :class:`alterlab.Actions` or a raw dict with a ``type`` discriminator.
                Supported types: ``wait``, ``wait_for``, ``click``, ``fill``, ``press``,
                ``scroll``, ``infinite_scroll``, ``screenshot``, ``evaluate``,
                ``dismiss_consent``, ``select``, ``hover``, ``click_text``, ``extract``,
                ``check``, ``uncheck``, ``wait_event``. ``wait_for`` accepts ``state``
                (``visible``, ``hidden``, ``attached``, ``detached``); ``press`` accepts an
                optional ``selector``. Selectors are CSS, or XPath when prefixed with ``//``
                or ``xpath=``. Actions execute sequentially; failed actions are skipped.
                Raw dict actions accept ``optional`` (default ``True``; ``False`` marks it
                required, see ``actions_on_error``), and ``click``/``fill``/``evaluate``
                accept ``timeout_ms`` (100-30000, default 10000). Results are returned in
                ``action_results`` as :class:`alterlab.ActionResult` entries, each with
                ``duration_ms``; ``extract`` returns its value in ``result`` and the
                response ``actions_status`` is ``complete``, ``partial`` or ``aborted``.
                Examples::

                    [
                        Actions.wait(milliseconds=1000),
                        {"type": "click", "selector": "button.load-more", "optional": False},
                        Actions.scroll(direction="down", amount=3),
                        {"type": "evaluate", "script": "document.title", "timeout_ms": 5000},
                        Actions.screenshot(),
                        Actions.select("select#size", label="M"),
                        Actions.wait_for(".spinner", state="hidden"),
                        Actions.extract("span.price"),
                    ]

            actions_on_error: What a failed required action does: ``"continue"`` (API
                default) skips it like an optional one; ``"abort"`` skips the remaining
                actions and fails the request with ``error_code=browser_actions_aborted``
                (not charged).

            headers: Custom HTTP request headers to forward to the target URL (max 50 headers).
                Header names must be 1-256 characters and header values must be at most 8192
                characters. Hop-by-hop and connection-control headers (e.g. ``Connection``,
                ``Transfer-Encoding``) are rejected by the API. Example::

                    {"Authorization": "Bearer token", "X-Custom-Header": "value"}

            agent_intent: Opt-in, opaque text describing what the calling agent is trying
                to do with this request. Sent as the ``X-Agent-Intent`` header to the
                AlterLab API itself (not forwarded to the target URL). Independent of
                ``agent_context``/``agent_feedback`` -- any subset may be sent. Truncated
                server-side at 500 characters; never rejected. Not parsed or interpreted,
                purely a telemetry signal (#28488). Non-ASCII text (accents, emoji, non-Latin
                scripts) is percent-encoded before being sent as an HTTP header, since header
                values must be US-ASCII; ASCII-only text is sent unmodified (#28634).
            agent_context: Opt-in, opaque text describing the broader context for this
                request (e.g. prior steps taken). Sent as the ``X-Agent-Context`` header.
                Same truncation, independence, and non-ASCII encoding rules as
                ``agent_intent``.
            agent_feedback: Opt-in, opaque text describing what already failed or what
                feedback the agent has from a previous attempt. Sent as the
                ``X-Agent-Feedback`` header. Same truncation, independence, and non-ASCII
                encoding rules as ``agent_intent``. Example::

                    result = await client.scrape(
                        "https://example.com/product",
                        agent_intent="Extract product price for comparison shopping",
                        agent_feedback="Previous attempt returned stale cached price",
                    )

            method: HTTP method to use when fetching the target URL. Defaults to ``"GET"``.
                Use ``"POST"`` for REST APIs, GraphQL endpoints, and form submissions.
                ``"DELETE"`` relays the method to the target server. Only use on endpoints
                you own or have explicit permission to modify.
                Accepted values: ``"GET"``, ``"POST"``, ``"PUT"``, ``"PATCH"``, ``"DELETE"``.
                Non-GET methods should be accompanied by a ``body`` parameter.
            body: Request body to send with non-GET HTTP methods. Must be a string —
                serialize JSON dicts with ``json.dumps()`` before passing. Ignored when
                ``method="GET"``. Example (GraphQL)::

                    import json
                    await client.scrape(
                        "https://api.example.com/graphql",
                        method="POST",
                        body=json.dumps({
                            "query": "{ user { id name } }",
                            "variables": {"id": 1},
                        }),
                        content_type="application/json",
                    )

            content_type: Content-Type header for the request body. Defaults to
                ``"application/json"`` when ``body`` is provided. Accepted values:
                ``"application/json"`` (GraphQL, REST APIs),
                ``"application/x-www-form-urlencoded"`` (HTML form submissions),
                ``"text/plain"`` (plain text payloads). Ignored when ``body`` is not set.
                Example (HTML form submission)::

                    await client.scrape(
                        "https://example.com/login",
                        method="POST",
                        body="username=alice&password=secret",
                        content_type="application/x-www-form-urlencoded",
                    )

            location: Geo-targeting parameters. Dict with optional keys:
                - ``country`` (str): ISO 3166-1 alpha-2 country code (e.g., ``"DE"``, ``"JP"``).
                  Routes the request through a proxy in that country.
                - ``language`` (str): ISO 639-1 language code (e.g., ``"de"``, ``"ja"``).
                  Sets the ``Accept-Language`` header and browser locale.
                Example: ``{"country": "DE", "language": "de"}``
            cache: Enable response caching. When ``True``, a cached result may be returned if
                available. Defaults to ``False`` (no caching). Use ``force_refresh=True`` to bypass
                an existing cache entry.
            cache_ttl: Cache TTL in seconds (60–86400). Only applies when ``cache=True``.
                Defaults to 3600 (1 hour) server-side when not specified. Alias of ``max_age``.
            max_age: Accept a stored result up to this many seconds old (0-86400). ``0`` always
                fetches fresh. A cache hit is billed at 50% of the price of the tier that produced
                the stored result and the response carries ``cached``, ``age_seconds``,
                ``fetched_at``, ``cache_tier`` and ``X-Cache: HIT``. When omitted, the API key's
                default applies (3600 for new keys, 0 for existing ones).
            webhook_url: URL to receive a ``job.completed`` or ``job.failed`` event when the
                scrape finishes. This is a server-side notification side-effect and does not
                affect client-side polling behavior — use ``sync=False`` to skip polling.
                HTTPS is required in production (``http://localhost`` is allowed in dev).
            max_response_bytes: Soft cap on raw response body size in bytes. When the
                downloaded HTML exceeds this value it is truncated before extraction and
                ``content_truncated.truncation_reason`` is set to ``'response_body_cap'``.
                Default: ``None`` (server default of 5 MB applies). Set to ``0`` for no
                limit. Maximum: 50 MB (52_428_800).
            template: Scrape template slug. When provided, the server looks up the
                template by slug and merges its ``request_config`` into the request
                body before processing. Caller-provided fields take precedence over
                template defaults. Example: ``"amazon-product"``.
            poll_interval: Initial polling interval for async jobs (seconds)
            poll_timeout: Maximum time to wait for async jobs (seconds)
            poll_backoff_multiplier: Multiplier for exponential backoff (default: 1.5)
            poll_max_interval: Maximum polling interval (seconds)

        Returns:
            Scrape response dictionary with content, metadata, and billing details.
            Key fields include:
            - ``url``, ``status_code``, ``content``, ``headers``, ``cached``
            - ``age_seconds``, ``fetched_at``, ``cache_tier``: freshness of the result (the
              ``X-Cache`` response header is ``HIT`` or ``MISS``).
            - ``cache_reason``: why a stored result was served when ``cached`` is true (the
              ``max_age`` in effect and whether it came from the request or the API key default).
            - ``revalidated`` (bool): ``True`` when the origin answered a conditional request
              with ``304 Not Modified`` and the stored body was served instead of a full fetch.
              Always ``False`` with ``force_refresh=True``.
            - ``final_url`` (Optional[str]): The URL after all redirects resolved.
              Equals ``url`` when no redirect occurred or when ``follow_redirects=false``.
            - ``redirected`` (Optional[bool]): ``True`` if the scraper followed one or
              more redirects before reaching the final page (``final_url != url``).
              ``False`` when no redirect occurred. ``None`` on error paths.
            - ``redirect_chain`` (Optional[List[Dict]]): Ordered list of redirect hops.
              Each entry is a dict with ``url`` (str) and ``status_code`` (int). Populated
              for T1–T3 (curl_cffi) tiers when redirects occur. ``None`` when no redirects
              occurred or when using the T4 (browser) tier. Example::

                  [
                      {"url": "http://example.com/old", "status_code": 301},
                      {"url": "https://example.com/new", "status_code": 200},
                  ]

            - ``tier_status_codes`` (Optional[Dict[str, int]]): Per-tier upstream HTTP
              status code trail, keyed by tier string (e.g. ``"1"``, ``"3"``, ``"3.5"``,
              ``"4"``). Reflects the upstream response status observed at each tier
              attempted during auto-escalation. ``None`` when no tier-attempt
              diagnostics were recorded for this job. Example::

                  {"1": 403, "3": 403, "4": 200}

            - ``credits_used``, ``response_time_ms``, ``size_bytes``
            - ``billing`` (:class:`BillingDetails`): Full billing breakdown including
              ``total_credits``, ``tier_used``, ``escalations``
              (``List[TierEscalationDetail]`` — each entry has ``tier``, ``result``,
              ``credits: int``, ``duration_ms: Optional[int]``, ``error:
              Optional[str]``), ``byop_applied``, and BYOP/BYOS discount fields.
            - ``warning`` (Optional[str]): Actionable warning when auto-escalation
              occurred, tier cap prevented escalation on thin content, or extraction
              quality is low.
            - ``tier_cap_warning`` (Optional[Dict]): Structured tier mismatch detail
              when ``max_tier`` or ``force_tier`` is below the domain's playbook
              minimum. Contains ``domain_min_tier`` (int) and either
              ``your_max_tier`` (float) or ``your_force_tier`` (int).
            - ``content_quality`` (Optional[Dict]): Content quality metadata from
              scrape diagnostics (e.g., word count, image count, quality score).
            - ``domain_warning`` (Optional[str]): Human-readable warning when the
              target domain has a low historical success rate. The scrape will still
              proceed, but results may be unreliable. See ``domain_difficulty`` for
              structured detail.
            - ``domain_difficulty`` (Optional[Dict]): Structured domain difficulty
              detail when ``domain_warning`` is set. Contains ``success_rate``
              (float 0.0–1.0), ``total_attempts`` (int), ``override_active`` (bool).
            - ``note`` (Optional[str]): Advisory message (e.g. when repeat-request
              detection identifies identical content across retries).
            - ``quality_warning`` (Optional[Dict]): Present when post-hoc soft-block
              detection fired on a successful scrape but the response contains usable
              content (word_count > 100). Full rate applies — AlterLab paid proxy/compute
              cost and the content is usable. Always contains: ``code`` (str, always
              ``'soft_block_posthoc'``), ``reason`` (str), ``word_count`` (int),
              ``content_size_bytes`` (int). Null for the majority of scrapes where no
              post-hoc soft-block was detected.
            - ``_meta`` (Optional[Dict]): Attribution metadata identifying AlterLab as
              the data provider. Auto-populated on every response. Contains
              ``provider`` (str, always ``"alterlab.io"``) and ``api_version``
              (str, e.g. ``"v1"``).
            - ``captured_cookies`` (Optional[Dict[str, str]]): Cookies set by the target
              during this scrape (the Set-Cookie jar), returned only when a
              ``sticky_session`` handle is used (see
              :class:`AdvancedOptions.sticky_session`). A subsequent ``scrape()`` call with
              the same ``sticky_session`` automatically replays these cookies (persisted
              server-side for the handle's TTL), so you rarely need to read them directly —
              they are surfaced for transparency and manual replay.

        Raises:
            AlterLabAPIError: On API errors
            JobTimeoutError: If async job polling times out (an AlterLabTimeoutError)
            AlterLabValidationError: If parameters are invalid
            AlterLabValidationError: If actions is provided but advanced.render_js is not set
            AlterLabValidationError: If more than 20 actions are provided

        Example:
            # Simple HTML scraping
            result = await client.scrape("https://example.com")

            # JavaScript rendering with screenshot
            result = await client.scrape(
                "https://example.com",
                mode="js",
                advanced=AdvancedOptions(render_js=True, screenshot=True)
            )

            # Structured extraction
            result = await client.scrape(
                "https://example.com/product",
                extraction_profile="product"
            )

            # Cost-controlled scraping
            result = await client.scrape(
                "https://example.com",
                cost_controls=CostControls(max_credits=5, fail_fast=True)
            )

            # Authenticated scraping with inline cookies
            result = await client.scrape(
                "https://amazon.com/dp/B0XXXXX",
                cookies={"session-id": "abc123", "session-token": "xyz789"}
            )

            # Authenticated scraping with stored session
            result = await client.scrape(
                "https://amazon.com/dp/B0XXXXX",
                session_id="uuid-of-stored-session"
            )

            # Geo-targeted scraping — retrieve German content via DE proxy
            result = await client.scrape(
                "https://example.com",
                location={"country": "DE", "language": "de"}
            )

            # Smart JS detection — renders only JS-heavy pages (30-60% cost savings)
            result = await client.scrape(
                "https://example.com",
                advanced=AdvancedOptions(render_js="auto")
            )

            # Cache-enabled scrape with custom TTL
            result = await client.scrape(
                "https://example.com",
                cache=True,
                cache_ttl=7200  # 2-hour cache
            )

            # Async scrape with webhook delivery (skips polling)
            result = await client.scrape(
                "https://example.com",
                sync=False,
                webhook_url="https://myapp.com/hooks/scrape-done"
            )
            # result contains {"job_id": "..."} — webhook delivers final result
        """
        if session_id and cookies:
            raise AlterLabValidationError(
                "Cannot provide both session_id and cookies. "
                "Use session_id to reference a stored session OR "
                "provide inline cookies, not both."
            )
        if actions is not None:
            if not advanced or not advanced.render_js:
                raise AlterLabValidationError(
                    "actions requires advanced.render_js=True or render_js='auto' "
                    "(browser rendering must be enabled to execute browser actions)"
                )
            if len(actions) > 20:
                raise AlterLabValidationError(
                    f"actions must contain at most 20 items, got {len(actions)}"
                )
            try:
                serialized_actions = serialize_actions(actions)
            except TypeError as exc:
                raise AlterLabValidationError(str(exc)) from exc
        if actions_on_error is not None and actions_on_error not in (
            "continue",
            "abort",
        ):
            raise AlterLabValidationError(
                f"actions_on_error must be 'continue' or 'abort', got {actions_on_error!r}"
            )
        if screenshot and (advanced is None or advanced.render_js is not True):
            raise AlterLabValidationError(
                "screenshot requires render_js=True. "
                "Pass advanced=AdvancedOptions(render_js=True, screenshot=True) "
                "or use scrape_js(screenshot=True) instead."
            )
        if cache_ttl is not None and not cache:
            raise AlterLabValidationError(
                "cache_ttl requires cache=True. "
                "Pass cache=True to enable caching, or omit cache_ttl."
            )
        if max_age is not None and max_age < 0:
            raise AlterLabValidationError(
                "max_age must be >= 0 seconds (0 always fetches fresh)."
            )
        _valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        if method.upper() not in _valid_methods:
            raise AlterLabValidationError(
                f"method must be one of {sorted(_valid_methods)}, got {method!r}. "
                "Use 'POST' for GraphQL/REST APIs and form submissions. "
                "DELETE relays the method to the target server — only use on endpoints you own or have explicit permission to modify."
            )
        method = method.upper()
        if body is not None and method == "GET":
            raise AlterLabValidationError(
                "body cannot be used with method='GET'. "
                "Use method='POST' (or PUT/PATCH) to send a request body."
            )

        if not sync and sync_policy == "wait_until_deadline":
            raise AlterLabValidationError(
                "sync_policy='wait_until_deadline' requires sync=True; "
                "use sync_policy='auto' when sync=False."
            )

        # Build request payload
        payload: Dict[str, Any] = {
            "url": url,
            "mode": mode,
            "sync": sync,
            "sync_policy": sync_policy,
            "force_refresh": force_refresh,
            "include_raw_html": include_raw_html,
            "timeout": timeout or self.timeout,
            "evidence": evidence,
            "promote_schema_org": promote_schema_org,
        }
        if response is not None:
            payload["response"] = response

        # Add advanced options
        if advanced:
            payload["advanced"] = advanced.to_dict()
        else:
            payload["advanced"] = {}

        # Add session/cookie params to advanced block
        if session_id:
            payload["advanced"]["session_id"] = session_id
        if cookies:
            payload["advanced"]["cookies"] = cookies
        if actions:
            payload["advanced"]["actions"] = serialized_actions
        if actions_on_error is not None:
            payload["advanced"]["actions_on_error"] = actions_on_error

        # Remove empty advanced block
        if not payload["advanced"]:
            del payload["advanced"]

        # Add cost controls
        if cost_controls:
            payload["cost_controls"] = cost_controls.to_dict()

        # Add optional parameters
        if formats:
            payload["formats"] = formats
        if extraction_schema:
            payload["extraction_schema"] = extraction_schema
        if extraction_prompt:
            payload["extraction_prompt"] = extraction_prompt
        if extraction_selectors is not None:
            payload["extraction_selectors"] = extraction_selectors
        if extraction_profile:
            payload["extraction_profile"] = extraction_profile

        # JS-specific options
        if wait_for:
            payload["wait_for"] = wait_for
        if screenshot:
            payload["screenshot"] = screenshot
        if wait_until:
            payload["wait_until"] = wait_until

        # PDF-specific options
        if mode == "pdf":
            payload["pdf_format"] = pdf_format

        # OCR-specific options
        if mode == "ocr":
            payload["ocr_language"] = ocr_language

        # Custom request headers forwarded to target URL
        if headers is not None:
            payload["headers"] = headers

        # HTTP method and request body
        if method != "GET":
            payload["method"] = method
        if body is not None:
            payload["body"] = body
        if content_type is not None:
            payload["content_type"] = content_type

        # Geo-targeting
        if location is not None:
            payload["location"] = location

        # Cache control
        if max_age is not None:
            payload["max_age"] = max_age
        if cache:
            payload["cache"] = cache
            if cache_ttl is not None:
                payload["cache_ttl"] = cache_ttl

        # Webhook URL for async notification
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url

        # Response body size cap
        if max_response_bytes is not None:
            payload["max_response_bytes"] = max_response_bytes

        # Template query parameter
        params: Dict[str, str] = {}
        if template is not None:
            params["template"] = template

        # Opt-in agent-intent signal (#28488) -- sent as request headers to the
        # AlterLab API itself, never added to the JSON body payload.
        #
        # HTTP header values must be US-ASCII (RFC 7230); passing a non-ASCII
        # string straight to httpx raises UnicodeEncodeError before the request
        # is ever sent. Percent-encode only when needed so ASCII-only values
        # (the common case) are sent byte-identical to before (#28634).
        agent_headers: Dict[str, str] = {}
        if agent_intent is not None:
            agent_headers["X-Agent-Intent"] = _ascii_safe_header_value(agent_intent)
        if agent_context is not None:
            agent_headers["X-Agent-Context"] = _ascii_safe_header_value(agent_context)
        if agent_feedback is not None:
            agent_headers["X-Agent-Feedback"] = _ascii_safe_header_value(agent_feedback)

        # Make request
        response = await self._request_with_retry(
            "POST",
            "/api/v1/scrape",
            json=payload,
            params=params if params else None,
            headers=agent_headers if agent_headers else None,
        )

        result = response.json()

        # Check if response is async (202 Accepted with job_id)
        if response.status_code == 202 and "job_id" in result:
            if not sync:
                # Return job info immediately in async mode.
                # When webhook_url is also provided alongside sync=True, the server
                # delivers the result via webhook as a side-effect, but polling still
                # proceeds so the caller receives the scraped content directly.
                return result

            # Poll for job completion with exponential backoff.
            #
            # This also transparently absorbs the server's sync-poll-timeout
            # downgrade (`sync_downgraded: true` — job_id + status=202 in place
            # of the old 504) (#31823): rather than surfacing the downgrade as
            # a distinct return shape, we keep polling so a sync caller still
            # gets the real scrape result instead of the bare downgrade
            # envelope. Log it so callers inspecting SDK debug output can see
            # the request was downgraded server-side, without changing the
            # return type.
            job_id = result["job_id"]
            if result.get("sync_downgraded"):
                logger.debug(
                    "sync_downgraded job_id=%s reason=%s — polling for real result",
                    job_id,
                    result.get("reason"),
                )
            # After a downgrade the job is already running at the dynamic tier, so
            # long-poll (`GET /jobs/{id}?wait=N`) to collect the result the moment
            # it lands instead of sleeping through a backoff interval (#37371).
            return await self.wait_for_job(
                job_id,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
                backoff_multiplier=poll_backoff_multiplier,
                max_interval=poll_max_interval,
                server_wait=(
                    _DOWNGRADE_LONG_POLL_SECONDS if result.get("sync_downgraded") else 0
                ),
            )

        # Synchronous response
        return parse_action_results(result)

    async def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 1.0,
        poll_timeout: float = 300.0,
        backoff_multiplier: float = 1.5,
        max_interval: float = 10.0,
        server_wait: int = 0,
    ) -> Dict[str, Any]:
        """Wait for async job completion with exponential backoff.

        ``server_wait`` (seconds, default 0 = off) long-polls
        ``GET /api/v1/jobs/{id}?wait=N`` so the result is returned the moment the
        job lands. ``scrape()`` enables it after a ``sync_downgraded`` 202. Servers
        that ignore ``wait`` answer immediately, so the backoff sleep still applies.

        This method polls the job status endpoint until the job completes or fails.
        It uses exponential backoff to reduce API load for long-running jobs.

        Args:
            job_id: Job ID to poll
            poll_interval: Initial polling interval in seconds
            poll_timeout: Maximum time to wait in seconds
            backoff_multiplier: Multiplier for exponential backoff
            max_interval: Maximum polling interval (caps exponential growth)

        Returns:
            The unwrapped ``result`` dict when the job succeeds — via
            ``job.get("result", job)``, so an explicit ``result: null`` in the
            server response is returned as ``None``, and only a genuinely
            *missing* ``result`` key falls back to the full job envelope.
            This differs from the Node SDK's ``waitForJob()``, which always
            returns the full ``JobStatusResponse`` envelope (``{job_id,
            status, result, error, ...}``), never just the unwrapped result.
            This is a pre-existing, intentional cross-language asymmetry
            (#31887) — read ``["result"]`` off Node's return value if you
            want Python-equivalent behavior there.

        Raises:
            JobExpiredError: If the job has expired on the server (1-hour TTL).
                Do not retry with the same job_id — submit a new request instead.
            AlterLabTimeoutError: If the SDK poll_timeout elapses before the job
                completes. The job may still be running on the server.
            JobFailedError: If the job reaches a terminal failure status
                (``failed``, ``rejected``, or ``cancelled``).
            AlterLabAPIError: On other API errors.
            AlterLabError: If the server reports a status outside the known
                ``JobStatus`` vocabulary (should not happen in practice).

        Example:
            # Start async job
            response = await client.scrape("https://example.com", sync=False)
            job_id = response["job_id"]

            # Wait for completion
            try:
                result = await client.wait_for_job(job_id)
            except JobExpiredError:
                # Job TTL exceeded — submit a fresh request
                result = await client.scrape("https://example.com")
        """
        start_time = time.time()
        current_interval = poll_interval

        while True:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > poll_timeout:
                raise JobTimeoutError(job_id, poll_timeout)

            # Get job status — surface 404 as JobExpiredError so callers can
            # distinguish "job gone, stop retrying" from transient API errors.
            poll_kwargs: Dict[str, Any] = {}
            if server_wait > 0:
                poll_kwargs["params"] = {"wait": server_wait}
                poll_kwargs["timeout"] = httpx.Timeout(server_wait + 15)
            poll_started = time.time()
            try:
                response = await self._request_with_retry(
                    "GET", f"/api/v1/jobs/{job_id}", **poll_kwargs
                )
            except AlterLabAPIError as exc:
                if exc.status_code == 404:
                    raise JobExpiredError(
                        404,
                        (
                            f"Job {job_id} has expired (TTL: 1 hour). "
                            "Submit a new request with client.scrape()."
                        ),
                        exc.response,
                    ) from exc
                raise

            job = response.json()
            status = job.get("status")
            # A long-poll that held the request open already did the waiting.
            long_polled = server_wait > 0 and time.time() - poll_started >= 1.0

            if status in _JOB_STATUS_SUCCEEDED:
                return parse_action_results(job.get("result", job))
            elif status in _JOB_STATUS_FAILED:
                error = job.get("error", f"Job ended with status '{status}'")
                raise JobFailedError(job_id, status, error)
            elif status in _JOB_STATUS_IN_PROGRESS:
                # Continue polling
                pass
            else:
                # Unknown status
                raise AlterLabError(f"Unknown job status: {status}")

            # Wait before next poll with exponential backoff
            if not long_polled:
                await asyncio.sleep(current_interval)
                current_interval = min(
                    current_interval * backoff_multiplier, max_interval
                )

    async def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        """Metadata of a ``download`` action artifact (see ``alterlab.artifacts``)."""
        return await _artifacts.get_artifact(self, artifact_id)

    async def get_artifact_url(self, artifact_id: str) -> Dict[str, Any]:
        """Short-lived signed download URL for an artifact."""
        return await _artifacts.get_artifact_url(self, artifact_id)

    async def download_artifact(self, artifact_id: str, path: Any) -> str:
        """Save an artifact to ``path``; returns the path written."""
        return await _artifacts.download_artifact(self, artifact_id, path)

    async def get_job_status(self, job_id: str, wait: int = 0) -> Dict[str, Any]:
        """Get the current status of an async job.

        By default this returns the current status immediately. Pass ``wait`` to
        long-poll on the server. Use wait_for_job() for automatic client-side polling.

        Args:
            job_id: Job ID to check
            wait: Seconds (>= 0) the server may hold the request for the job to reach a
                terminal status (``GET /api/v1/jobs/{id}?wait=N``). The server caps it;
                0 (default) returns immediately.

        Returns:
            Job status dictionary with keys: status, result (if completed), error (if failed)

        Raises:
            JobExpiredError: If the job has expired on the server (1-hour TTL).
            AlterLabAPIError: On other API errors.

        Example:
            try:
                status = await client.get_job_status("job_123")
            except JobExpiredError:
                # Job is gone — submit a new request
                ...
            print(f"Status: {status['status']}")
            if status['status'] == 'completed':
                result = status['result']
        """
        if wait < 0:
            raise ValueError("wait must be >= 0")
        request_kwargs: Dict[str, Any] = {}
        if wait > 0:
            request_kwargs["params"] = {"wait": wait}
            request_kwargs["timeout"] = httpx.Timeout(wait + 15)
        try:
            response = await self._request_with_retry(
                "GET", f"/api/v1/jobs/{job_id}", **request_kwargs
            )
        except AlterLabAPIError as exc:
            if exc.status_code == 404:
                raise JobExpiredError(
                    404,
                    (
                        f"Job {job_id} has expired (TTL: 1 hour). "
                        "Submit a new request with client.scrape()."
                    ),
                    exc.response,
                ) from exc
            raise
        return response.json()

    async def estimate_cost(
        self,
        url: str,
        mode: Literal["auto", "html", "js", "pdf", "ocr"] = "auto",
        advanced: Optional[AdvancedOptions] = None,
        cost_controls: Optional[CostControls] = None,
        formats: Optional[List[OutputFormat]] = None,
        extraction_selectors: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Estimate cost for a scrape request without executing it.

        This method provides a cost estimate based on the URL and options.
        Use this before scraping to avoid unexpected credit charges.

        Args:
            url: URL to estimate
            mode: Scraping mode
            advanced: Advanced options to include in estimate
            cost_controls: Optional cost controls for estimation (max_credits, max_tier, etc.)
            formats: Optional output formats for transformation (text, json, json_v2, html, markdown, rag, content, raw, document)
            extraction_selectors: Deterministic ``{field: selector}`` map to include in the estimate

        Returns:
            Cost estimate dictionary with keys:
            - url: URL being estimated
            - estimated_tier: Expected tier (e.g., "1", "2")
            - estimated_credits: Expected credit cost
            - confidence: Confidence level (low, medium, high)
            - max_possible_credits: Maximum credits if all escalations occur
            - min_credits, likely_credits, max_credits: Param-aware cost range
              (``likely_credits`` equals ``estimated_credits``, ``max_credits`` equals
              ``max_possible_credits``)
            - drivers: List of ``{"name", "detail"}`` factors that shaped the range
            - reasoning: Explanation of estimate

        Raises:
            AlterLabAPIError: On API errors

        Example:
            estimate = await client.estimate_cost(
                "https://example.com",
                mode="js",
                advanced=AdvancedOptions(render_js=True, screenshot=True)
            )
            print(f"Estimated: {estimate['estimated_credits']} credits")
            print(f"Max possible: {estimate['max_possible_credits']} credits")
        """
        payload: Dict[str, Any] = {"url": url, "mode": mode}

        if advanced:
            payload["advanced"] = advanced.to_dict()

        if cost_controls:
            payload["cost_controls"] = cost_controls.to_dict()

        if formats:
            payload["formats"] = formats

        if extraction_selectors is not None:
            payload["extraction_selectors"] = extraction_selectors

        response = await self._request_with_retry(
            "POST", "/api/v1/scrape/estimate", json=payload
        )

        return response.json()

    async def hands_request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Call a Hands endpoint (``/api/v1/hands`` + ``path``) and return its JSON."""
        kwargs = {"json": body} if body is not None else {}
        response = await self._request_with_retry(
            method, f"/api/v1/hands{path}", **kwargs
        )
        return response.json()

    async def get_usage(self) -> Dict[str, Any]:
        """Get current usage statistics and credit balance.

        All monetary values are in **microcents** (1,000,000 microcents = $1.00).
        To convert to dollars: ``usage['balance_microcents'] / 1_000_000``.

        Returns:
            Usage stats dictionary with keys:
            - balance_microcents: Current non-expiring PAYG wallet balance
            - credits_available: Deprecated alias for balance_microcents
            - credits_used_month: Actual microcents spent this billing period
            - account_tier: Canonical balance tier slug
            - entitlement_source: Source of the account entitlement
            - period_start: Start of the current billing period (ISO 8601)
            - period_end: End of the current billing period (ISO 8601)

        Raises:
            AlterLabAPIError: On API errors

        Example:
            usage = await client.get_usage()
            balance = usage['balance_microcents'] / 1_000_000
            print(f"Balance: ${balance:.4f}")
            print(f"Account tier: {usage['account_tier']}")
        """
        response = await self._request_with_retry("GET", "/api/v1/usage")

        return response.json()

    async def batch_scrape(
        self, requests: List[Dict[str, Any]], webhook_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Submit multiple scrape requests as a batch.

        Batch requests are processed asynchronously. You can provide a webhook URL
        to receive notifications when the batch completes.

        Args:
            requests: List of scrape request dictionaries. Each dict should contain
                     the same parameters as scrape() method (url, mode, advanced, etc.),
                     including ``extraction_selectors``
            webhook_url: Optional webhook URL for completion notification

        Returns:
            Batch job information with keys:
            - batch_id: Unique batch identifier
            - total_urls: Number of URLs submitted in the batch
            - job_ids: Job IDs for the accepted URLs
            - status: Batch status (e.g. processing)
            - estimated_credits: Credits pre-debited for the accepted URLs
            - accepted_urls: Count of URLs admitted and dispatched as jobs
            - rejected_urls: Count of URLs rejected before dispatch

        Raises:
            AlterLabAPIError: On API errors

        Example:
            requests = [
                {"url": "https://example.com/page1", "mode": "html"},
                {"url": "https://example.com/page2", "mode": "js"},
                {"url": "https://example.com/page3", "mode": "html"}
            ]
            batch = await client.batch_scrape(
                requests,
                webhook_url="https://myapp.com/webhook"
            )
            print(f"Batch ID: {batch['batch_id']}")

            # Check individual job statuses
            for job_id in batch['job_ids']:
                status = await client.get_job_status(job_id)
                print(f"Job {job_id}: {status['status']}")
        """
        # The API BatchRequest field is ``urls``; the parameter name stays ``requests``
        # for backward compatibility (#35843).
        payload: Dict[str, Any] = {"urls": requests}

        if webhook_url:
            payload["webhook_url"] = webhook_url

        response = await self._request_with_retry("POST", "/api/v1/batch", json=payload)

        return response.json()

    # Convenience methods with preset configurations

    async def scrape_html(
        self, url: str, use_proxy: bool = False, **kwargs
    ) -> Dict[str, Any]:
        """Scrape HTML content without JavaScript rendering.

        This is a convenience method for simple HTTP requests. It's the fastest
        and most cost-effective option (1 credit base).

        Args:
            url: URL to scrape
            use_proxy: Use premium proxy (+1 credit)
            **kwargs: Additional arguments passed to scrape()

        Returns:
            Scrape response

        Example:
            result = await client.scrape_html("https://example.com")
            print(result['content'])
        """
        advanced = AdvancedOptions(use_proxy=use_proxy)
        return await self.scrape(url, mode="html", advanced=advanced, **kwargs)

    async def scrape_js(
        self,
        url: str,
        screenshot: bool = False,
        markdown: bool = False,
        wait_for: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Scrape content with JavaScript rendering.

        This convenience method renders JavaScript using a headless browser.
        Base cost is 4 credits, plus additional costs for screenshot/markdown.

        Args:
            url: URL to scrape
            screenshot: Capture full-page screenshot (+1 credit)
            markdown: Convert to markdown (free)
            wait_for: CSS selector to wait for before capturing content
            **kwargs: Additional arguments passed to scrape()

        Returns:
            Scrape response

        Example:
            # Render JS and capture screenshot
            result = await client.scrape_js(
                "https://example.com",
                screenshot=True,
                wait_for=".content-loaded"
            )
            screenshot_url = result['screenshot_url']
        """
        advanced = AdvancedOptions(
            render_js=True, screenshot=screenshot, markdown=markdown
        )
        return await self.scrape(
            url, mode="js", advanced=advanced, wait_for=wait_for, **kwargs
        )

    async def scrape_pdf(
        self, url: str, format: str = "markdown", **kwargs
    ) -> Dict[str, Any]:
        """Extract content from PDF files.

        This convenience method extracts text from PDF documents.
        Base cost is 3 credits.

        Args:
            url: PDF URL
            format: Output format (text or markdown)
            **kwargs: Additional arguments passed to scrape()

        Returns:
            Scrape response with extracted PDF content

        Example:
            result = await client.scrape_pdf(
                "https://example.com/document.pdf",
                format="markdown"
            )
            print(result['content'])
        """
        return await self.scrape(url, mode="pdf", pdf_format=format, **kwargs)

    async def scrape_ocr(
        self, url: str, language: str = "eng", **kwargs
    ) -> Dict[str, Any]:
        """Extract text from images using OCR.

        This convenience method performs optical character recognition on images.
        Base cost is 6 credits.

        Args:
            url: Image URL
            language: OCR language code (eng, fra, deu, spa, etc.)
            **kwargs: Additional arguments passed to scrape()

        Returns:
            Scrape response with OCR-extracted text

        Example:
            result = await client.scrape_ocr(
                "https://example.com/image.png",
                language="eng"
            )
            print(result['content'])
            print(result['ocr_results'])  # Detailed OCR results with bounding boxes
        """
        return await self.scrape(url, mode="ocr", ocr_language=language, **kwargs)

    # ---- Crawl methods ----

    async def crawl(
        self,
        url: str,
        max_pages: int = 50,
        max_depth: int = 3,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        formats: Optional[List[OutputFormat]] = None,
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_profile: Optional[
            Literal[
                "auto",
                "product",
                "article",
                "job_posting",
                "faq",
                "recipe",
                "event",
                "ecommerce_homepage",
                "directory_listing",
            ]
        ] = None,
        webhook_url: Optional[str] = None,
        advanced: Optional[Dict[str, Any]] = None,
        respect_robots: bool = True,
        include_subdomains: bool = False,
        cost_controls: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Start a website crawl.

        Discovers pages via sitemap and link extraction, then scrapes them all.
        Returns immediately with a crawl_id for polling progress.

        Args:
            url: Start URL for the crawl
            max_pages: Maximum number of pages to scrape (1-100000, default 50)
            max_depth: Maximum link-following depth (0-50, default 3)
            include_patterns: Glob patterns — only URLs matching at least one are scraped
            exclude_patterns: Glob patterns — URLs matching any are skipped
            formats: Output formats for each page (text, json, json_v2, html, markdown, rag, content, raw, document)
            extraction_schema: JSON Schema for structured extraction on each page
            extraction_profile: Pre-defined extraction profile for each page
            webhook_url: URL to receive crawl.completed webhook
            advanced: Advanced scraping options applied to every page (render_js,
                screenshot, use_proxy, wait_for, timeout)
            respect_robots: Respect robots.txt rules (default True)
            include_subdomains: Include links to subdomains (default False)
            cost_controls: Cost controls dict with max_credits, max_tier, force_tier,
                time_budget

        Returns:
            Crawl response with crawl_id, status, estimated_pages, etc.

        Raises:
            AlterLabAPIError: On API errors
            AlterLabValidationError: If parameters are invalid

        Example:
            crawl = await client.crawl(
                "https://example.com",
                max_pages=200,
                max_depth=2,
                include_patterns=["/products/*"],
                formats=["markdown", "json"],
                advanced={"render_js": "auto", "timeout": 120},
            )
            print(f"Crawl ID: {crawl['crawl_id']}")
            print(f"Pages found: {crawl['estimated_pages']}")
        """
        payload: Dict[str, Any] = {
            "url": url,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "respect_robots": respect_robots,
            "include_subdomains": include_subdomains,
        }

        if include_patterns is not None:
            payload["include_patterns"] = include_patterns
        if exclude_patterns is not None:
            payload["exclude_patterns"] = exclude_patterns
        if formats is not None:
            payload["formats"] = formats
        if extraction_schema is not None:
            payload["extraction_schema"] = extraction_schema
        if extraction_profile is not None:
            payload["extraction_profile"] = extraction_profile
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if advanced is not None:
            payload["advanced"] = advanced
        if cost_controls is not None:
            payload["cost_controls"] = cost_controls

        response = await self._request_with_retry("POST", "/api/v1/crawl", json=payload)

        return response.json()

    async def get_crawl(
        self,
        crawl_id: str,
        include_results: bool = False,
    ) -> Dict[str, Any]:
        """Get crawl status and optionally per-page results.

        Args:
            crawl_id: Crawl ID returned from crawl()
            include_results: Include per-page scrape results (default False)

        Returns:
            Crawl status with progress counters and optional page results

        Raises:
            AlterLabAPIError: On API errors (404 if crawl not found/expired)

        Example:
            status = await client.get_crawl(crawl.crawl_id)
            print(f"Status: {status['status']}")
            print(f"Progress: {status['completed']}/{status['total']}")
        """
        params = {}
        if include_results:
            params["include_results"] = "true"

        response = await self._request_with_retry(
            "GET", f"/api/v1/crawl/{crawl_id}", params=params
        )

        return response.json()

    async def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        """Cancel a crawl and refund credits for unprocessed pages.

        Jobs already completed or in-progress are not affected.

        Args:
            crawl_id: Crawl ID to cancel

        Returns:
            Cancel response with cancelled_jobs count and credits_refunded

        Raises:
            AlterLabAPIError: On API errors (404 if not found, 409 if already complete)

        Example:
            result = await client.cancel_crawl(crawl_id)
            print(f"Cancelled {result['cancelled_jobs']} jobs")
            print(f"Refunded {result['credits_refunded']} credits")
        """
        response = await self._request_with_retry("DELETE", f"/api/v1/crawl/{crawl_id}")

        return response.json()

    async def export_crawl(
        self,
        crawl_id: str,
        format: Literal["json", "jsonl", "csv"] = "json",
        status: Literal[
            "succeeded",
            "failed",
            "rejected",
            "expired",
            "queued",
            "processing",
            "cancelled",
            "all",
        ] = "succeeded",
        fields: Optional[str] = None,
    ) -> bytes:
        """Export crawl results as a downloadable file.

        Fetches all page results for a completed (or in-progress) crawl and
        returns them as raw bytes in the requested format. Suitable for saving
        to disk or streaming to a client.

        Args:
            crawl_id: Crawl ID returned from crawl()
            format: Output format — "json" (array), "jsonl" (newline-delimited JSON),
                or "csv". Default: "json".
            status: Filter pages by status. One of: "succeeded", "failed",
                "rejected", "expired", "queued", "processing", "cancelled", "all".
                Default: "succeeded". Use "all" to include every page.
            fields: Optional comma-separated list of fields to include in output
                (e.g. "url,html,status"). Omit to include all fields.

        Returns:
            Raw bytes of the export file. Decode with UTF-8 for text formats.

        Raises:
            AlterLabAPIError: On API errors (404 if crawl not found/expired)

        Example:
            # Download as JSON
            data = await client.export_crawl(crawl_id, format="json")
            import json
            rows = json.loads(data.decode("utf-8"))

            # Download as CSV
            csv_data = await client.export_crawl(crawl_id, format="csv", status="all")
            with open("results.csv", "wb") as f:
                f.write(csv_data)
        """
        params: Dict[str, Any] = {"format": format, "status": status}
        if fields is not None:
            params["fields"] = fields

        response = await self._request_with_retry(
            "GET", f"/api/v1/crawl/{crawl_id}/export", params=params
        )

        return response.content

    async def crawl_stream(
        self,
        crawl_id: str,
    ):
        """Stream real-time crawl events via Server-Sent Events.

        Returns an async iterator that yields parsed SSE events as
        dictionaries with ``event`` (str) and ``data`` (dict) keys.

        Event types:
        - ``page.completed`` — per-page result with metadata, cost, tier
        - ``page.failed`` — per-page failure with error reason
        - ``crawl.progress`` — periodic summary (pages done/total, cost)
        - ``crawl.completed`` — final summary; iteration stops after this

        Args:
            crawl_id: Crawl ID returned from crawl()

        Yields:
            Dict with 'event' (str) and 'data' (dict) keys

        Raises:
            AlterLabAPIError: On HTTP errors (404 if crawl not found)

        Example:
            crawl = await client.crawl("https://example.com", max_pages=10)
            async for event in client.crawl_stream(crawl["crawl_id"]):
                if event["event"] == "page.completed":
                    print(f"Scraped: {event['data']['url']}")
                elif event["event"] == "crawl.completed":
                    print(f"Done: {event['data']['completed']}/{event['data']['total']}")
        """
        import json as _json

        url = f"/api/v1/crawl/{crawl_id}/stream"
        headers = {
            "X-API-Key": self._api_key,
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=None
        ) as stream_client:
            async with stream_client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise AlterLabAPIError(
                        f"SSE stream failed: {response.status_code}",
                        status_code=response.status_code,
                        response_body=body.decode("utf-8", errors="replace"),
                    )

                current_event = "message"
                data_lines: list[str] = []

                async for raw_line in response.aiter_lines():
                    line = raw_line.rstrip("\n").rstrip("\r")

                    # Comment or keepalive
                    if line.startswith(":"):
                        continue

                    # Empty line = event boundary
                    if not line:
                        if data_lines:
                            data_str = "\n".join(data_lines)
                            try:
                                parsed = _json.loads(data_str)
                            except _json.JSONDecodeError:
                                parsed = data_str
                            yield {"event": current_event, "data": parsed}

                            # Terminal event — stop iteration
                            if current_event == "crawl.completed":
                                return

                            current_event = "message"
                            data_lines = []
                        continue

                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())

    async def crawl_and_wait(
        self,
        url: str,
        max_pages: int = 50,
        max_depth: int = 3,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        formats: Optional[List[OutputFormat]] = None,
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_profile: Optional[
            Literal[
                "auto",
                "product",
                "article",
                "job_posting",
                "faq",
                "recipe",
                "event",
                "ecommerce_homepage",
                "directory_listing",
            ]
        ] = None,
        webhook_url: Optional[str] = None,
        advanced: Optional[Dict[str, Any]] = None,
        respect_robots: bool = True,
        include_subdomains: bool = False,
        cost_controls: Optional[Dict[str, Any]] = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 600.0,
        poll_backoff_multiplier: float = 1.5,
        poll_max_interval: float = 15.0,
    ) -> Dict[str, Any]:
        """Start a crawl and wait for completion, returning all results.

        Convenience method that combines crawl() + polling get_crawl() until
        all pages are done. Uses exponential backoff for polling.

        Args:
            url: Start URL for the crawl
            max_pages: Maximum pages to scrape (default 50)
            max_depth: Maximum link depth (default 3)
            include_patterns: Glob patterns to include
            exclude_patterns: Glob patterns to exclude
            formats: Output formats per page
            extraction_schema: JSON Schema for extraction
            extraction_profile: Pre-defined extraction profile
            webhook_url: URL to receive crawl.completed webhook
            advanced: Advanced scraping options applied to every page (render_js,
                screenshot, use_proxy, wait_for, timeout)
            respect_robots: Respect robots.txt (default True)
            include_subdomains: Include subdomains (default False)
            cost_controls: Cost controls dict
            poll_interval: Initial polling interval in seconds (default 2.0)
            poll_timeout: Maximum wait time in seconds (default 600.0)
            poll_backoff_multiplier: Backoff multiplier (default 1.5)
            poll_max_interval: Max polling interval in seconds (default 15.0)

        Returns:
            Final crawl status with all per-page results included

        Raises:
            AlterLabTimeoutError: If crawl doesn't complete within timeout
            AlterLabAPIError: On API errors

        Example:
            results = await client.crawl_and_wait(
                "https://example.com",
                max_pages=50,
                formats=["markdown"],
            )
            for page in results.get("pages", []):
                print(f"{page['url']}: {page['status']}")
        """
        crawl_response = await self.crawl(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            formats=formats,
            extraction_schema=extraction_schema,
            extraction_profile=extraction_profile,
            webhook_url=webhook_url,
            advanced=advanced,
            respect_robots=respect_robots,
            include_subdomains=include_subdomains,
            cost_controls=cost_controls,
        )

        crawl_id = crawl_response["crawl_id"]
        start_time = time.time()
        current_interval = poll_interval

        while True:
            elapsed = time.time() - start_time
            if elapsed > poll_timeout:
                raise AlterLabTimeoutError(
                    f"Crawl {crawl_id} did not complete within {poll_timeout} seconds"
                )

            await asyncio.sleep(current_interval)

            status = await self.get_crawl(crawl_id, include_results=True)
            crawl_status = status.get("status", "")

            if crawl_status in ("completed", "partial", "failed"):
                return status

            current_interval = min(
                current_interval * poll_backoff_multiplier, poll_max_interval
            )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: Optional[str] = None,
        *,
        queries: Optional[List[str]] = None,
        engine: Optional[Literal["duckduckgo", "google", "bing", "auto"]] = None,
        safe_search: Optional[bool] = None,
        domain: Optional[str] = None,
        num_results: int = 10,
        page: int = 1,
        country: Optional[str] = None,
        language: Optional[str] = None,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]] = None,
        scrape_results: Optional[bool] = None,
        formats: Optional[List[OutputFormat]] = None,
        extraction_schema: Optional[Dict[str, Any]] = None,
        device: Optional[Literal["desktop", "mobile"]] = None,
        num: Optional[int] = None,
        start: Optional[int] = None,
        wait: Optional[int] = None,
        mode: Optional[Literal["fast", "standard", "deep"]] = None,
        live: Optional[bool] = None,
        concise: bool = True,
        sync: bool = False,
    ) -> Dict[str, Any]:
        """Search the web: unified, vendor-neutral results with page content by default.

        A plain ``search("query")`` runs the unified search (``engine="auto"``) on
        ``/v1/search`` and returns each result page as concise markdown with a per-result
        ``content_status`` (``scrape_results=True``, ``concise=True``, ``mode="standard"``).
        Pass ``scrape_results=False`` for the result list only. An explicit ``engine`` of
        "duckduckgo", "google" or "bing" keeps that engine's behaviour: content is only
        fetched when you ask for it, and plain requests use ``/v1/serp``.

        Args:
            query: Search terms (max 500 characters); give exactly one of ``query`` or ``queries``
            queries: 1-5 queries run in one request and billed as one unit; returns the multi
                response (``results`` = per-query ``{query, status, error, response}``)
            engine: "auto" (default) for the unified, vendor-neutral search, or
                "duckduckgo" ($0.001/query), "google" or "bing" ($0.004/query)
            safe_search: Enable the engine's safe-search filter
            domain: Restrict results to a specific domain (applied as site: prefix)
            num_results: Number of results to return (1-30, default 10)
            page: Result page number (1-indexed, default 1)
            country: ISO 3166-1 alpha-2 country code for geo-targeted results
            language: Language code for results (e.g., en, fr, de)
            time_range: Filter results by recency
            scrape_results: Return each result page's content. Default: True for the unified
                engine with a single ``query``; False for an explicit engine or ``queries``.
            formats: Output formats when scrape_results=True (includes "rag")
            extraction_schema: JSON schema for structured extraction (when scrape_results=True)
            concise: With scrape_results, use the concise agent preset (markdown with size
                caps). False returns full-length content.
            device: "desktop" (default) or "mobile" SERP layout (only on the /v1/serp path)
            num: Alias for num_results (takes precedence when both are given)
            start: 0-based offset of the first result; a multiple of the result count,
                takes precedence over page
            wait: With scrape_results=True, seconds (1-60) to wait for result pages and
                return content inline (HTTP 200). Pages not done are returned with
                ``content_status="pending"``; poll ``get_search``. Omit for the async flow.
            mode: Latency tier for inline content: "fast" (5 s), "standard" (15 s) or
                "deep" (60 s); an explicit ``wait`` overrides it.
            live: With scrape_results=True, False allows cached page content
                (default: fetch live). Each result reports ``fetched_at``.
            sync: With ``scrape_results=True``, wait up to a bounded budget (about 30s)
                and return content in one call; on timeout the response is a 202 with
                ``next_action`` (poll ``get_search``)

        Returns:
            Search response with search_id, results, credits_used, etc. Content searches
            add ``content_coverage`` and per-result ``content_status``
            (ok | partial | blocked | timeout | dead_origin | pending).

        Raises:
            AlterLabAPIError: On API errors

        Example:
            results = await client.search("web scraping api python")
            for r in results["results"]:
                print(f"{r['position']}. {r['title']} — {r['url']}")
        """
        if (query is None) == (queries is None):
            raise ValueError("search() takes exactly one of query or queries")
        # Unified search with content is the default (#38613); an explicit engine opts out.
        engine = "auto" if engine is None else engine
        if scrape_results is None:
            scrape_results = engine == "auto" and queries is None
        payload: Dict[str, Any] = {
            "num_results": num if num is not None else num_results,
            "page": page,
            "scrape_results": scrape_results,
            "engine": engine,
        }
        if scrape_results and engine == "auto":
            if concise and formats is None:
                payload["preset"] = "agent"
            if wait is None and mode is None:
                mode = "standard"
        if queries is not None:
            payload["queries"] = queries
        else:
            payload["query"] = query
        if start is not None:
            payload["start"] = start
        if sync:
            payload["sync"] = True
        # /v1/serp has no multi-query form; `queries` is served by /v1/search.
        # engine="auto" (unified metasearch) is only served by /v1/search.
        use_serp = (
            not scrape_results
            and domain is None
            and time_range is None
            and queries is None
            and engine != "auto"
        )
        if device is not None and use_serp:
            payload["device"] = device
        if safe_search is not None:
            payload["safe_search"] = safe_search
        if domain is not None:
            payload["domain"] = domain
        if country is not None:
            payload["country"] = country
        if language is not None:
            payload["language"] = language
        if time_range is not None:
            payload["time_range"] = time_range
        if formats is not None:
            payload["formats"] = formats
        if extraction_schema is not None:
            payload["extraction_schema"] = extraction_schema
        if wait is not None:
            payload["wait"] = wait
        if mode is not None:
            payload["mode"] = mode
        if live is not None:
            payload["live"] = live

        path = "/api/v1/serp" if use_serp else "/api/v1/search"
        response = await self._request_with_retry("POST", path, json=payload)
        return response.json()

    async def batch_search(
        self,
        queries: List[str],
        *,
        engine: Optional[Literal["duckduckgo", "google", "bing"]] = None,
        safe_search: Optional[bool] = None,
        num_results: int = 10,
        country: Optional[str] = None,
        language: Optional[str] = None,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]] = None,
        scrape_results: bool = False,
        formats: Optional[List[OutputFormat]] = None,
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a batch of search queries for async parallel processing.

        Args:
            queries: List of search queries (1-50)
            engine: "duckduckgo" (default), "google" or "bing"; applies to all queries
            safe_search: Enable the engine's safe-search filter
            num_results: Number of results per query (1-30, default 10)
            country: ISO 3166-1 alpha-2 country code
            language: Language code
            time_range: Filter results by recency
            scrape_results: Scrape each result page
            formats: Output formats when scrape_results=True (includes "rag")
            webhook_url: URL to receive batch.search.completed webhook (counts and
                status only; poll get_batch_search() for results)

        Returns:
            Batch response with batch_id, job_ids, status, etc.

        Raises:
            AlterLabAPIError: On API errors
        """
        payload: Dict[str, Any] = {
            "queries": queries,
            "num_results": num_results,
            "scrape_results": scrape_results,
        }
        if engine is not None:
            payload["engine"] = engine
        if safe_search is not None:
            payload["safe_search"] = safe_search
        if country is not None:
            payload["country"] = country
        if language is not None:
            payload["language"] = language
        if time_range is not None:
            payload["time_range"] = time_range
        if formats is not None:
            payload["formats"] = formats
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url

        response = await self._request_with_retry(
            "POST", "/api/v1/search/batch", json=payload
        )
        return response.json()

    async def get_search(self, search_id: str) -> Dict[str, Any]:
        """Poll a search started with scrape_results=True (GET /api/v1/search/{id})."""
        response = await self._request_with_retry("GET", f"/api/v1/search/{search_id}")
        return response.json()

    async def get_batch_search(self, batch_id: str) -> Dict[str, Any]:
        """Poll a batch search (GET /api/v1/search/batch/{batch_id}).

        Returns status, per-query counts and per-query results in ``items``.
        """
        response = await self._request_with_retry(
            "GET", f"/api/v1/search/batch/{batch_id}"
        )
        return response.json()

    # ------------------------------------------------------------------
    # Map
    # ------------------------------------------------------------------

    async def map(
        self,
        url: str,
        *,
        max_pages: int = 500,
        max_depth: int = 3,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        search: Optional[str] = None,
        sitemap: Literal["skip", "include", "only"] = "include",
        sitemap_path: Optional[str] = None,
        include_metadata: bool = False,
        include_subdomains: bool = False,
        respect_robots: bool = True,
    ) -> Dict[str, Any]:
        """Discover URLs on a website via sitemap parsing and link extraction.

        Lightweight site structure discovery without scraping content.
        Returns a flat list of discovered URLs with optional metadata.

        Args:
            url: Starting URL for site discovery
            max_pages: Maximum URLs to discover (1-50000, default 500)
            max_depth: Link-following depth (0-10, default 3)
            include_patterns: Glob patterns — only include matching URLs
            exclude_patterns: Glob patterns — exclude matching URLs
            search: Query to filter/rank discovered URLs by relevance
            sitemap: Sitemap handling: skip, include (default), or only
            sitemap_path: Custom sitemap location (e.g., /custom-sitemap.xml)
            include_metadata: Fetch title and meta description for each URL
            include_subdomains: Include URLs from subdomains
            respect_robots: Respect robots.txt directives (default True)

        Returns:
            Map response with map_id, urls, total_urls, credits_used, etc.

        Raises:
            AlterLabAPIError: On API errors

        Example:
            result = await client.map(
                "https://example.com",
                max_pages=1000,
                include_metadata=True,
            )
            for entry in result["urls"]:
                print(f"{entry['url']} (depth={entry['depth']})")
        """
        payload: Dict[str, Any] = {
            "url": url,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "sitemap": sitemap,
            "include_metadata": include_metadata,
            "include_subdomains": include_subdomains,
            "respect_robots": respect_robots,
        }
        if include_patterns is not None:
            payload["include_patterns"] = include_patterns
        if exclude_patterns is not None:
            payload["exclude_patterns"] = exclude_patterns
        if search is not None:
            payload["search"] = search
        if sitemap_path is not None:
            payload["sitemap_path"] = sitemap_path

        response = await self._request_with_retry("POST", "/api/v1/map", json=payload)
        return response.json()

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------

    async def extract(
        self,
        content: str,
        *,
        content_type: Literal["html", "text", "markdown"] = "html",
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_profile: Optional[
            Literal[
                "auto",
                "product",
                "article",
                "job_posting",
                "faq",
                "recipe",
                "event",
                "ecommerce_homepage",
                "directory_listing",
            ]
        ] = None,
        extraction_template: Optional[
            Literal[
                "auto",
                "product",
                "article",
                "job_posting",
                "faq",
                "recipe",
                "event",
                "ecommerce_homepage",
                "directory_listing",
            ]
        ] = None,
        extraction_prompt: Optional[str] = None,
        extraction_provider: Optional[
            Literal["openai", "anthropic", "openrouter", "groq"]
        ] = None,
        extraction_model: Optional[str] = None,
        formats: Optional[List[OutputFormat]] = None,
        source_url: Optional[str] = None,
        evidence: bool = False,
        cache: Literal["auto", "skip", "only"] = "auto",
        cache_ttl: Optional[int] = None,
        extraction_selectors: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Extract structured data from raw content without scraping.

        Accepts HTML, text, or markdown content and runs the extraction pipeline
        including format conversion, schema-based filtering, and LLM extraction.

        Args:
            content: Raw content to extract from (HTML, text, or markdown)
            content_type: Type of the provided content (default "html")
            extraction_schema: JSON Schema for structured extraction
            extraction_profile: Pre-defined extraction profile
            extraction_template: Shorthand for extraction_profile. Selects a pre-built
                schema template by name. Mutually exclusive with extraction_profile.
            extraction_prompt: Natural language extraction instructions for LLM
            extraction_provider: LLM provider to use for extraction ("openai",
                "anthropic", "openrouter", or "groq"). Selects the matching BYOK key
                registered in dashboard settings. When omitted, the most recently used
                registered key is used automatically.
            extraction_model: Per-request LLM model override in provider-specific
                format (e.g. "gpt-4o", "claude-opus-4-5-20251101", "llama3-70b-8192").
                Overrides the model saved in BYOK key settings for this request only.
            extraction_selectors: Deterministic ``{field: selector}`` map (1-100 fields),
                no LLM or BYOK key needed. Each selector has exactly one of ``css`` /
                ``xpath`` plus optional ``attr`` and ``multiple``.
            formats: Output formats (default ["json"])
            source_url: Original URL of the content (for context, not fetched)
            evidence: Include field provenance/evidence (default False)
            cache: Cache control for LLM extraction results. "auto" returns cached
                result if available (default). "skip" bypasses cache lookup, always
                calls LLM (result still stored for future callers). "only" returns
                cached result or HTTP 404 — never calls the LLM.
            cache_ttl: TTL for caching this extraction result, in seconds (1–86400).
                Defaults to the server-side LLM_EXTRACTION_CACHE_TTL env var (3600s).

        Returns:
            Extract response with extract_id, formats, credits_used, etc.

        Raises:
            AlterLabAPIError: On API errors

        Example:
            result = await client.extract(
                content="<html><body><h1>Price: $29.99</h1></body></html>",
                content_type="html",
                extraction_prompt="Extract the price",
                extraction_provider="openai",
                formats=["json"],
                cache="skip",
            )
            print(result["formats"]["json"])
        """
        payload: Dict[str, Any] = {
            "content": content,
            "content_type": content_type,
            "evidence": evidence,
            "cache": cache,
        }
        if extraction_schema is not None:
            payload["extraction_schema"] = extraction_schema
        if extraction_profile is not None:
            payload["extraction_profile"] = extraction_profile
        if extraction_template is not None:
            payload["extraction_template"] = extraction_template
        if extraction_prompt is not None:
            payload["extraction_prompt"] = extraction_prompt
        if extraction_selectors is not None:
            payload["extraction_selectors"] = extraction_selectors
        if extraction_provider is not None:
            payload["extraction_provider"] = extraction_provider
        if extraction_model is not None:
            payload["extraction_model"] = extraction_model
        if formats is not None:
            payload["formats"] = formats
        if source_url is not None:
            payload["source_url"] = source_url
        if cache_ttl is not None:
            payload["cache_ttl"] = cache_ttl

        response = await self._request_with_retry(
            "POST", "/api/v1/extract", json=payload
        )
        return response.json()

    # ---------------------------------------------------------------------------
    # Extraction estimate, usage, and template methods
    # ---------------------------------------------------------------------------

    async def estimate_extraction_cost(
        self,
        content_length: int,
        has_extraction_prompt: bool = False,
    ) -> Dict[str, Any]:
        """Estimate the cost of a POST /v1/extract call before committing to it.

        This endpoint is read-only — it does not require a registered BYOK key
        and does not modify the user's balance.

        Args:
            content_length: Length of the content in characters (1–5,000,000)
            has_extraction_prompt: Whether an extraction_prompt or LLM profile will be used

        Returns:
            EstimateResponse with estimated_cost_microcents, estimated_cost_usd, and breakdown

        Raises:
            AlterLabAPIError: On API errors
        """
        params: Dict[str, Any] = {
            "content_length": content_length,
            "has_extraction_prompt": has_extraction_prompt,
        }
        response = await self._request_with_retry(
            "GET", "/api/v1/extract/estimate", params=params
        )
        return response.json()

    async def get_extraction_usage(
        self,
        page: int = 1,
        page_size: int = 50,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated extraction usage history for the authenticated user.

        Results are ordered by created_at DESC (newest first).

        Args:
            page: Page number (1-indexed, default 1)
            page_size: Records per page (1–200, default 50)
            date_from: ISO 8601 date string for range start (e.g. '2025-01-01')
            date_to: ISO 8601 date string for range end (e.g. '2025-12-31')

        Returns:
            ExtractionUsageListResponse with items, total, page, page_size, has_more

        Raises:
            AlterLabAPIError: On API errors
        """
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if date_from is not None:
            params["date_from"] = date_from
        if date_to is not None:
            params["date_to"] = date_to
        response = await self._request_with_retry(
            "GET", "/api/v1/extract/usage", params=params
        )
        return response.json()

    async def get_extraction_usage_summary(
        self,
        hours: Optional[int] = None,
        days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get aggregate extraction usage totals for the authenticated user.

        Accepts hours or days to scope the period — mutually exclusive.

        Args:
            hours: Look back N hours (1–8760, mutually exclusive with days)
            days: Look back N days (1–365, mutually exclusive with hours)

        Returns:
            ExtractionUsageSummaryResponse with total_requests and total_cost_microcents

        Raises:
            AlterLabAPIError: On API errors
        """
        params: Dict[str, Any] = {}
        if hours is not None:
            params["hours"] = hours
        if days is not None:
            params["days"] = days
        response = await self._request_with_retry(
            "GET", "/api/v1/extract/usage/summary", params=params
        )
        return response.json()

    # Deprecated methods for backwards compatibility

    async def scrape_light(self, url: str, **kwargs) -> Dict[str, Any]:
        """DEPRECATED: Use scrape() or scrape_html() instead.

        This method is deprecated and will be removed in version 3.0.
        Use scrape(url, mode="html") or scrape_html(url) instead.

        Args:
            url: URL to scrape
            **kwargs: Additional arguments

        Returns:
            Scrape response
        """
        warnings.warn(
            "scrape_light() is deprecated and will be removed in version 3.0. "
            "Use scrape(url, mode='html') or scrape_html(url) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.scrape_html(url, **kwargs)

    # ── Scrape Templates (public, no auth required) ──────────────────────

    async def list_scrape_templates(
        self,
        page: int = 1,
        page_size: int = 20,
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List public scrape templates with optional tag filtering.

        No authentication required.

        Args:
            page: Page number (1-based, default 1)
            page_size: Items per page (1–100, default 20)
            tag: Optional tag to filter templates by

        Returns:
            Dict with ``templates`` list, ``total``, ``page``, and ``page_size``.
            Each template contains: ``id``, ``slug``, ``name``, ``description``,
            ``url_pattern``, ``request_config``, ``tags``, ``use_count``,
            ``created_by_team``, ``created_at``, ``updated_at``.

        Raises:
            AlterLabAPIError: On API errors
        """
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if tag is not None:
            params["tag"] = tag
        response = await self._request_with_retry(
            "GET", "/api/v1/templates", params=params
        )
        return response.json()

    async def get_scrape_template(self, slug: str) -> Dict[str, Any]:
        """Get a single public scrape template by its slug.

        No authentication required.

        Args:
            slug: URL-safe unique identifier of the template

        Returns:
            Dict with template fields: ``id``, ``slug``, ``name``,
            ``description``, ``url_pattern``, ``request_config``, ``tags``,
            ``use_count``, ``created_by_team``, ``created_at``, ``updated_at``.

        Raises:
            AlterLabAPIError: On API errors (404 if template not found)
        """
        response = await self._request_with_retry("GET", f"/api/v1/templates/{slug}")
        return response.json()

    async def feedback(
        self,
        category: str,
        tried: Optional[str],
        happened: str,
        expected: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Report friction to AlterLab (POST /api/v1/agent/feedback).

        The public feedback API has no category or job fields, so ``category``
        prefixes the clustered ``happened`` text and ``job_id`` is appended to
        ``tried``. Free text is capped at 1000 characters. Never include
        customer data.

        Returns:
            ``report_id``, ``cluster_key``, ``status`` and ``status_url``
            (GET it to follow the report's status).

        Example:
            result = await client.feedback(
                "blocked", "mode=auto", "empty body with 200", job_id="job_123"
            )
            print(result["status_url"])
        """
        limit = 1000
        tried_text = tried or ""
        if job_id:
            tried_text = f"{tried_text} job_id={job_id}".strip()
        payload: Dict[str, Any] = {
            "what_failed": f"[{category}] {happened}"[:limit],
            "surface": "sdk",
        }
        if tried_text:
            payload["what_tried"] = tried_text[:limit]
        if expected:
            payload["what_expected"] = expected[:limit]
        response = await self._request_with_retry(
            "POST", "/api/v1/agent/feedback", json=payload
        )
        data = response.json()
        data[
            "status_url"
        ] = f"{self.base_url}/api/v1/agent/feedback/{data['cluster_key']}"
        return data

    async def close(self):
        """Close the HTTP client.

        Call this method when you're done using the client to free up resources.
        Alternatively, use the client as an async context manager.

        Example:
            client = AlterLab(api_key="sk_test_...")
            try:
                result = await client.scrape("https://example.com")
            finally:
                await client.close()
        """
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Synchronous wrapper for convenience
class AlterLabSync:
    """Synchronous wrapper for AlterLab client.

    This wrapper provides synchronous methods for developers who prefer
    synchronous code or are working in non-async environments.

    Note: This still uses asyncio internally, so performance is identical
    to the async client. Consider using the async client directly for better
    integration with async codebases.

    Example:
        with AlterLabSync(api_key="sk_test_...") as client:
            result = client.scrape("https://example.com")
            print(result['content'])

        # Or, with ALTERLAB_API_KEY set in the environment:
        with AlterLabSync() as client:
            result = client.scrape("https://example.com")
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize synchronous client.

        Args:
            api_key: Your API key. If not provided, reads from the
                ``ALTERLAB_API_KEY`` environment variable.
            **kwargs: Additional arguments passed to AlterLab()
        """
        self._client = AlterLab(api_key, **kwargs)
        self._loop = asyncio.new_event_loop()

        # Resource namespaces
        self.sessions = SyncSessions(self._client.sessions, self._run)
        for _ns in (
            "account",
            "support",
            "jobs",
            "monitors",
            "schedules",
            "store",
            "feeds",
            "workflows",
        ):
            setattr(self, _ns, SyncNamespace(getattr(self._client, _ns), self._run))

    def _run(self, coro):
        """Run async coroutine synchronously."""
        return self._loop.run_until_complete(coro)

    @overload
    def scrape(
        self, url: str, *args: Any, sync: Literal[False], **kwargs: Any
    ) -> ScrapeAcceptedResponse: ...

    @overload
    def scrape(self, *args: Any, **kwargs: Any) -> Dict[str, Any]: ...

    def scrape(self, *args, **kwargs):
        """Synchronous version of scrape()."""
        return self._run(self._client.scrape(*args, **kwargs))

    def support_ticket(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of support_ticket()."""
        return self._run(self._client.support_ticket(*args, **kwargs))

    def report_scrape(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of report_scrape()."""
        return self._run(self._client.report_scrape(*args, **kwargs))

    def pricing(self) -> Dict[str, Any]:
        """Synchronous version of pricing()."""
        return self._run(self._client.pricing())

    def news(self, *args, **kwargs) -> Any:
        """Synchronous version of news()."""
        return self._run(self._client.news(*args, **kwargs))

    def keyword_ideas(self, **fields) -> Any:
        """Synchronous version of keyword_ideas()."""
        return self._run(self._client.keyword_ideas(**fields))

    def serp(self, *args, **kwargs) -> Any:
        """Synchronous version of serp()."""
        return self._run(self._client.serp(*args, **kwargs))

    def ai_visibility(self, *args, **kwargs) -> Any:
        """Synchronous version of ai_visibility()."""
        return self._run(self._client.ai_visibility(*args, **kwargs))

    def screenshot(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of screenshot()."""
        return self._run(self._client.screenshot(*args, **kwargs))

    def estimate_cost(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of estimate_cost()."""
        return self._run(self._client.estimate_cost(*args, **kwargs))

    def hands_request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Synchronous version of hands_request()."""
        return self._run(self._client.hands_request(method, path, body))

    def get_usage(self) -> Dict[str, Any]:
        """Synchronous version of get_usage()."""
        return self._run(self._client.get_usage())

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        """Synchronous version of get_artifact()."""
        return self._run(self._client.get_artifact(artifact_id))

    def get_artifact_url(self, artifact_id: str) -> Dict[str, Any]:
        """Synchronous version of get_artifact_url()."""
        return self._run(self._client.get_artifact_url(artifact_id))

    def download_artifact(self, artifact_id: str, path: Any) -> str:
        """Synchronous version of download_artifact()."""
        return self._run(self._client.download_artifact(artifact_id, path))

    def get_job_status(self, job_id: str, wait: int = 0) -> Dict[str, Any]:
        """Synchronous version of get_job_status()."""
        return self._run(self._client.get_job_status(job_id, wait=wait))

    def wait_for_job(self, job_id: str, **kwargs) -> Dict[str, Any]:
        """Synchronous version of wait_for_job()."""
        return self._run(self._client.wait_for_job(job_id, **kwargs))

    def batch_scrape(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of batch_scrape()."""
        return self._run(self._client.batch_scrape(*args, **kwargs))

    def crawl(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of crawl()."""
        return self._run(self._client.crawl(*args, **kwargs))

    def get_crawl(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_crawl()."""
        return self._run(self._client.get_crawl(*args, **kwargs))

    def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        """Synchronous version of cancel_crawl()."""
        return self._run(self._client.cancel_crawl(crawl_id))

    def export_crawl(self, crawl_id: str, **kwargs) -> bytes:
        """Synchronous version of export_crawl().

        Returns raw bytes of the export file. See AlterLabClient.export_crawl()
        for full parameter documentation.
        """
        return self._run(self._client.export_crawl(crawl_id, **kwargs))

    def crawl_and_wait(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of crawl_and_wait()."""
        return self._run(self._client.crawl_and_wait(*args, **kwargs))

    def search(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of search()."""
        return self._run(self._client.search(*args, **kwargs))

    def research(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of research()."""
        return self._run(self._client.research(*args, **kwargs))

    def get_research(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_research()."""
        return self._run(self._client.get_research(*args, **kwargs))

    def cancel_research(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of cancel_research()."""
        return self._run(self._client.cancel_research(*args, **kwargs))

    def wait_for_research(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of wait_for_research()."""
        return self._run(self._client.wait_for_research(*args, **kwargs))

    def research_events(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """Synchronous version of research_events()."""
        return self._run(self._client.research_events(*args, **kwargs))

    def get_research_plan(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_research_plan()."""
        return self._run(self._client.get_research_plan(*args, **kwargs))

    def update_research_plan(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of update_research_plan()."""
        return self._run(self._client.update_research_plan(*args, **kwargs))

    def approve_research(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of approve_research()."""
        return self._run(self._client.approve_research(*args, **kwargs))

    def batch_search(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of batch_search()."""
        return self._run(self._client.batch_search(*args, **kwargs))

    def get_search(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_search()."""
        return self._run(self._client.get_search(*args, **kwargs))

    def get_batch_search(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_batch_search()."""
        return self._run(self._client.get_batch_search(*args, **kwargs))

    def map(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of map()."""
        return self._run(self._client.map(*args, **kwargs))

    def extract(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of extract()."""
        return self._run(self._client.extract(*args, **kwargs))

    def estimate_extraction_cost(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of estimate_extraction_cost()."""
        return self._run(self._client.estimate_extraction_cost(*args, **kwargs))

    def get_extraction_usage(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_extraction_usage()."""
        return self._run(self._client.get_extraction_usage(*args, **kwargs))

    def get_extraction_usage_summary(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of get_extraction_usage_summary()."""
        return self._run(self._client.get_extraction_usage_summary(*args, **kwargs))

    def scrape_html(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of scrape_html()."""
        return self._run(self._client.scrape_html(*args, **kwargs))

    def scrape_js(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of scrape_js()."""
        return self._run(self._client.scrape_js(*args, **kwargs))

    def scrape_pdf(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of scrape_pdf()."""
        return self._run(self._client.scrape_pdf(*args, **kwargs))

    def scrape_ocr(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of scrape_ocr()."""
        return self._run(self._client.scrape_ocr(*args, **kwargs))

    def list_scrape_templates(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of list_scrape_templates()."""
        return self._run(self._client.list_scrape_templates(*args, **kwargs))

    def get_scrape_template(self, slug: str) -> Dict[str, Any]:
        """Synchronous version of get_scrape_template()."""
        return self._run(self._client.get_scrape_template(slug))

    def feedback(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous version of feedback()."""
        return self._run(self._client.feedback(*args, **kwargs))

    def close(self):
        """Close the client and event loop."""
        self._run(self._client.close())
        self._loop.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
