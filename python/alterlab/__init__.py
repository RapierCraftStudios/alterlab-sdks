"""AlterLab Python SDK.

A production-ready Python client for the AlterLab Scraping API with full feature support.

Example:
    import asyncio
    from alterlab import AlterLab, AdvancedOptions, CostControls

    async def main():
        async with AlterLab(api_key="sk_test_...") as client:
            # Simple scraping
            result = await client.scrape("https://example.com")
            print(result['content'])

            # Authenticated scraping with cookies
            result = await client.scrape(
                "https://amazon.com/dp/B0XXXXX",
                cookies={"session-id": "abc123", "session-token": "xyz789"}
            )

            # Session management
            session = await client.sessions.create(
                name="My Amazon Prime",
                domain="amazon.com",
                cookies={"session-id": "abc123"},
            )

    asyncio.run(main())

For synchronous usage:
    from alterlab import AlterLabSync

    with AlterLabSync(api_key="sk_test_...") as client:
        result = client.scrape("https://example.com")
        print(result['content'])

For a drop-in ``requests`` replacement (zero setup beyond an env var):
    from alterlab import requests

    response = requests.get("https://example.com")
    print(response.status_code, response.text)
"""

from alterlab import actions as _actions
from alterlab._namespaces import UnexpectedResponseHook
from alterlab import artifacts
from alterlab import requests_compat as requests
from alterlab.actions import *  # noqa: F401,F403  (names listed in actions.__all__)
from alterlab.artifacts import download_artifact, get_artifact, get_artifact_url
from alterlab.client import (
    AdvancedOptions,
    AlterLab,
    AlterLabAPIError,
    AlterLabError,
    AlterLabSync,
    AlterLabTimeoutError,
    AlterLabValidationError,
    AuthenticationError,
    CostControls,
    ForcedRenderHint,
    InsufficientFundsError,
    JobExpiredError,
    JobFailedError,
    RateLimitError,
    get_error_hint,
)
from alterlab import document_types
from alterlab.document_types import (
    DocumentBlock,
    DocumentLink,
    DocumentMedia,
    DocumentV1,
)
from alterlab.requests_compat import AlterLabHTTPError
from alterlab.types import (
    ContentImage,
    ContentLink,
    ContentResult,
    EmbeddingsError,
    ExtractionMetadata,
    SessionIntegration,
    SessionListResponse,
    SessionValidation,
)

__version__ = "2.4.5"
__all__ = [
    "AlterLab",
    "AlterLabSync",
    "UnexpectedResponseHook",
    "AdvancedOptions",
    "CostControls",
    "AlterLabError",
    "AlterLabAPIError",
    "AlterLabHTTPError",
    "AlterLabTimeoutError",
    "AlterLabValidationError",
    "AuthenticationError",
    "InsufficientFundsError",
    "RateLimitError",
    "JobExpiredError",
    "JobFailedError",
    "ForcedRenderHint",
    "get_error_hint",
    "SessionIntegration",
    "SessionListResponse",
    "SessionValidation",
    "EmbeddingsError",
    "ContentResult",
    "ContentImage",
    "ContentLink",
    "ExtractionMetadata",
    "document_types",
    "DocumentV1",
    "DocumentBlock",
    "DocumentLink",
    "DocumentMedia",
    "requests",
    "artifacts",
    "get_artifact",
    "get_artifact_url",
    "download_artifact",
]
__all__ += _actions.__all__
