"""Type definitions for AlterLab SDK session and cookie support."""

from typing import Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict


class ContentImage(TypedDict, total=False):
    """A single image extracted by the content format.

    Returned inside :class:`ContentResult`'s ``images`` list when
    ``formats=["content"]`` is requested.
    """

    url: str
    """Absolute URL of the image."""

    alt: Optional[str]
    """Alt text, or ``None`` if absent."""

    role: Literal["hero", "content", "logo", "unknown"]
    """Semantic role classified by MediaExtractor."""


class ContentLink(TypedDict, total=False):
    """A single link extracted by the content format.

    Returned inside :class:`ContentResult`'s ``links`` list when
    ``formats=["content"]`` is requested.
    """

    url: str
    """Absolute URL of the link."""

    text: str
    """Visible anchor text."""

    role: Literal["content", "cta", "social", "nav", "unknown"]
    """Semantic role classified by the link classifier."""


class ContentResult(TypedDict, total=False):
    """Structured output from ``formats=["content"]``.

    The ``content`` format is a deterministic AI/KB pipeline mode that extracts
    Readability-cleaned markdown alongside structured image context and classified
    links.  A SHA-256 ``content_hash`` is included for cheap change detection —
    store it and compare on re-scrapes instead of diffing full bodies.

    Access from the scrape response via ``result["content"]["content"]`` when
    ``formats=["content"]`` is requested::

        result = await client.scrape(
            "https://example.com",
            formats=["content"],
        )
        content: ContentResult = result["content"]["content"]
        print(content["body_markdown"])   # Readability markdown
        print(content["content_hash"])    # SHA-256 for change detection

    Fields
    ------
    body_markdown:
        Readability-cleaned markdown of the page body.  Uses the same pipeline
        as the ``markdown`` format but without the outer document envelope.
    content_hash:
        Hex-encoded SHA-256 of ``body_markdown``.  Stable across identical
        content; changes when the body changes.
    word_count:
        Approximate word count of the cleaned body text.
    images:
        Structured image list with ``url``, ``alt``, and ``role`` fields.
    links:
        Classified link list with ``url``, ``text``, and ``role`` fields.
    """

    body_markdown: str
    """Readability-cleaned markdown of the page body."""

    content_hash: str
    """Hex-encoded SHA-256 of ``body_markdown`` for change detection."""

    word_count: int
    """Approximate word count of the cleaned body text."""

    images: List[ContentImage]
    """Structured image list classified by MediaExtractor."""

    links: List[ContentLink]
    """Classified link list with semantic roles."""


class TierInfo(TypedDict):
    """Rate-limit tier information derived from account balance.

    Returned as part of the ``/auth/me`` response so that SDK consumers can
    inspect their current tier without a separate API call.

    Balance-based tier table:

    +--------------+-----------+-------+-------------+
    | Tier         | Balance   |  RPM  | Concurrent  |
    +==============+===========+=======+=============+
    | Free         | $0–$5     |  30   |      3      |
    | Basic        | $5–$50    |  60   |     10      |
    | Growth       | $50–$200  | 100   |     15      |
    | Scale        | $200–$500 | 300   |     25      |
    | High Volume  | $500+     | 500   |     50      |
    | Enterprise   | Custom    | 10000 |    500      |
    +--------------+-----------+-------+-------------+
    """

    name: str
    """Human-readable tier name, e.g. ``'Free'``, ``'Basic'``, ``'Growth'``."""

    slug: str
    """Machine-readable tier identifier, e.g. ``'free'``, ``'basic'``, ``'growth'``."""

    requests_per_minute: int
    """Maximum API requests per minute allowed at this tier."""

    concurrent_requests: int
    """Maximum number of concurrent scrape requests allowed at this tier."""

    min_balance_usd: float
    """Minimum account balance (USD) required to qualify for this tier."""

    max_balance_usd: Optional[float]
    """Upper balance threshold (USD) for this tier. ``None`` means no upper limit."""

    next_tier_slug: Optional[str]
    """Slug of the next higher tier, or ``None`` if already at the top tier."""

    next_tier_threshold_usd: Optional[float]
    """Balance (USD) needed to reach the next tier, or ``None`` if at top tier."""


class SessionIntegration(TypedDict, total=False):
    """A stored session integration. Cookie values are never exposed."""

    id: str
    name: str
    domain: str
    cookie_names: List[str]
    header_names: Optional[List[str]]
    status: Literal["active", "expired", "invalid", "pending_validation"]
    expires_at: Optional[str]
    last_validated_at: Optional[str]
    validation_confidence: Optional[int]
    consecutive_failures: int
    last_used_at: Optional[str]
    total_requests: int
    successful_requests: int
    success_rate: float
    notes: Optional[str]
    created_at: str
    updated_at: str


class SessionListResponse(TypedDict):
    """Response from listing sessions."""

    sessions: List[SessionIntegration]
    total: int


class SessionValidation(TypedDict, total=False):
    """Result of a session validation check."""

    is_valid: bool
    confidence: int
    http_status: Optional[int]
    detected_user: Optional[str]
    cookie_expiry_detected: Optional[str]
    cookies_expiring_soon: bool
    indicators_found: Optional[Dict[str, List[str]]]
    consecutive_failures: int
    details: str


class EmbeddingsError(TypedDict):
    """Why embeddings were requested but not returned (key or provider failure).

    Present as ``result["embeddings_error"]`` on a scrape response when
    ``embeddings`` was requested but generation failed after a key resolved.
    The scrape result is still returned and the embeddings add-on is not charged.
    """

    code: Literal["no_api_key", "invalid_key", "quota", "provider_error"]
    message: str


class ExtractionMetadata(TypedDict, total=False):
    """Per-call extraction transparency metadata returned in ``POST /v1/extract`` responses.

    Provides full context about how the extraction was performed: which LLM provider
    and model were used, token counts reported by the provider, AlterLab's invocation
    fee, end-to-end latency, and whether a cached result was served.

    Token counts are ``None`` when no LLM was invoked (algorithmic extraction) or when
    the provider did not report usage (some OpenRouter models omit usage fields).

    Access via ``result["extraction_metadata"]`` in the :py:meth:`~alterlab.AlterLab.extract`
    response::

        result = await client.extract(
            "https://example.com",
            formats=["markdown"],
        )
        meta: ExtractionMetadata = result.get("extraction_metadata", {})
        print(meta.get("provider"))         # e.g. 'openai'
        print(meta.get("cost_microcents"))  # invocation fee
    """

    mode: str
    """Extraction mode: ``'byok'`` when a BYOK key was used, ``'algorithmic'`` otherwise."""

    provider: Optional[str]
    """LLM provider used (openai, anthropic, openrouter, groq), or ``None`` if no LLM ran."""

    model: Optional[str]
    """LLM model ID used for extraction, or ``None`` if no LLM ran."""

    input_tokens: Optional[int]
    """Prompt token count reported by the provider, or ``None`` if unavailable."""

    output_tokens: Optional[int]
    """Completion token count reported by the provider, or ``None`` if unavailable."""

    cost_microcents: int
    """AlterLab invocation fee charged in microcents (net of any refunds)."""

    cached: bool
    """Whether a cached extraction result was served."""

    latency_ms: int
    """End-to-end extraction latency in milliseconds."""
