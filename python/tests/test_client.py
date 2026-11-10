"""Unit tests for the core AlterLab SDK client constructors.

Covers the ``ALTERLAB_API_KEY`` environment-variable fallback added to
``AlterLab.__init__`` and ``AlterLabSync.__init__``, mirroring the coverage
already established for the crewai and llama-index wrapper packages
(``sdk/crewai/crewai_alterlab``, ``sdk/llama-index-readers-alterlab``).
"""

import pytest

from alterlab import AdvancedOptions, AlterLab, AlterLabSync


def test_advanced_options_preserve_proxy_intent_on_wire():
    """Omitted proxy intent differs from explicit false/true in SDK payloads."""
    omitted = AdvancedOptions(render_js=True).to_dict()
    explicit_false = AdvancedOptions(use_proxy=False).to_dict()
    explicit_true = AdvancedOptions(use_proxy=True).to_dict()

    assert "use_proxy" not in omitted
    assert explicit_false["use_proxy"] is False
    assert explicit_true["use_proxy"] is True
    assert omitted["render_js"] is True


def test_advanced_options_omission_keeps_public_boolean_attribute():
    """The compatibility attribute remains false when the option was omitted."""
    options = AdvancedOptions()

    assert options.use_proxy is False
    assert "use_proxy" not in options.to_dict()


def test_advanced_options_public_mutation_is_explicit_on_wire():
    """Mutating the compatibility attribute opts into explicit proxy intent."""
    options = AdvancedOptions()
    options.use_proxy = True
    assert options.to_dict()["use_proxy"] is True

    options.use_proxy = False
    assert options.to_dict()["use_proxy"] is False


# ---------------------------------------------------------------------------
# AlterLab (async client) construction tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_client_explicit_api_key():
    """AlterLab uses the explicit api_key argument when provided."""
    client = AlterLab(api_key="sk_live_explicit")
    try:
        assert client.api_key == "sk_live_explicit"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_async_client_uses_env_var_when_api_key_omitted(monkeypatch):
    """AlterLab falls back to ALTERLAB_API_KEY when api_key is omitted."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    client = AlterLab()
    try:
        assert client.api_key == "sk_live_from_env"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_async_client_explicit_api_key_wins_over_env(monkeypatch):
    """An explicit api_key argument takes precedence over ALTERLAB_API_KEY."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    client = AlterLab(api_key="sk_live_explicit")
    try:
        assert client.api_key == "sk_live_explicit"
    finally:
        await client.close()


def test_async_client_missing_api_key_raises(monkeypatch):
    """AlterLab raises ValueError when no api_key and no env var are set."""
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AlterLab API key is required"):
        AlterLab()


# ---------------------------------------------------------------------------
# AlterLabSync construction tests
# ---------------------------------------------------------------------------


def test_sync_client_explicit_api_key():
    """AlterLabSync uses the explicit api_key argument when provided."""
    client = AlterLabSync(api_key="sk_live_explicit")
    try:
        assert client._client.api_key == "sk_live_explicit"
    finally:
        client.close()


def test_sync_client_uses_env_var_when_api_key_omitted(monkeypatch):
    """AlterLabSync falls back to ALTERLAB_API_KEY when api_key is omitted."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    client = AlterLabSync()
    try:
        assert client._client.api_key == "sk_live_from_env"
    finally:
        client.close()


def test_sync_client_explicit_api_key_wins_over_env(monkeypatch):
    """An explicit api_key argument takes precedence over ALTERLAB_API_KEY."""
    monkeypatch.setenv("ALTERLAB_API_KEY", "sk_live_from_env")
    client = AlterLabSync(api_key="sk_live_explicit")
    try:
        assert client._client.api_key == "sk_live_explicit"
    finally:
        client.close()


def test_sync_client_missing_api_key_raises(monkeypatch):
    """AlterLabSync raises ValueError when no api_key and no env var are set."""
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AlterLab API key is required"):
        AlterLabSync()


def test_skip_tls_verification_is_three_state_on_the_wire():
    # Omitted lets the API fall back automatically for invalid certificates.
    assert "skip_tls_verification" not in AdvancedOptions().to_dict()
    assert (
        AdvancedOptions(skip_tls_verification=True).to_dict()["skip_tls_verification"]
        is True
    )
    assert (
        AdvancedOptions(skip_tls_verification=False).to_dict()["skip_tls_verification"]
        is False
    )


def test_insufficient_funds_error_surfaces_topup_url_and_welcome_offer():
    import httpx

    from alterlab import InsufficientFundsError

    offer = {"expires_at": "2026-10-29T00:00:00+00:00", "match_pct": 100}
    body = {
        "detail": {
            "error": "insufficient_credits",
            "message": "Balance empty. Top up: https://x/billing?quick_topup=1000&tl=t",
            "topup_url": "https://x/billing?quick_topup=1000&tl=t",
            "welcome_offer": offer,
        }
    }
    response = httpx.Response(402, json=body)
    err = InsufficientFundsError(402, "Balance empty.", response)
    assert err.topup_url == "https://x/billing?quick_topup=1000&tl=t"
    assert err.welcome_offer == offer
    assert err.billing_url == "https://alterlab.io/dashboard/billing"


def test_insufficient_funds_error_without_new_fields_keeps_defaults():
    import httpx

    from alterlab import InsufficientFundsError

    err = InsufficientFundsError(402, "x", httpx.Response(402, json={"detail": "x"}))
    assert err.topup_url is None
    assert err.welcome_offer is None
    assert err.billing_url == "https://alterlab.io/dashboard/billing"
