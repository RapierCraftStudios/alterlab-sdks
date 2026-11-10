"""#40215: ``embeddings_error`` is typed and passes through scrape responses."""

import httpx
import pytest

from alterlab import AlterLab
from alterlab import EmbeddingsError

_ERR = {"code": "invalid_key", "message": "OpenAI rejected your key."}


def test_embeddings_error_type_shape():
    assert set(EmbeddingsError.__annotations__) == {"code", "message"}


@pytest.mark.asyncio
async def test_embeddings_error_passes_through():
    client = AlterLab(api_key="sk_test_x", max_retries=1)
    body = {
        "url": "https://example.com",
        "status_code": 200,
        "content": {"markdown": "ok"},
        "embeddings": None,
        "embeddings_error": _ERR,
    }
    client.client = httpx.AsyncClient(
        base_url=client.base_url,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    result = await client.scrape("https://example.com")
    err: EmbeddingsError = result["embeddings_error"]
    assert err == _ERR
