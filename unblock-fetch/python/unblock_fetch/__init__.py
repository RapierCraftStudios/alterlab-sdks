"""unblock-fetch: fetch directly, fall back to AlterLab only when blocked."""

from unblock_fetch import client as _client
from unblock_fetch import detector as _detector

__version__ = "0.1.0"

get = _client.fetch_with_fallback
is_blocked = _detector.detect_block
UnblockResponse = _client.FetchResult

__all__ = ["get", "is_blocked", "UnblockResponse", "__version__"]
