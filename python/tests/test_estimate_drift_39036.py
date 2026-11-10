"""#39036: SDK docs mention the fields added by #39027."""

from alterlab import client


def test_estimate_cost_docs_mention_range_fields():
    doc = client.AlterLab.estimate_cost.__doc__ or ""
    for key in ("min_credits", "likely_credits", "max_credits", "drivers"):
        assert key in doc


def test_billing_details_docs_mention_estimated_credits():
    assert "estimated_credits" in (client.BillingDetails.__doc__ or "")


def test_scrape_docs_mention_cache_reason():
    assert "cache_reason" in (client.AlterLab.scrape.__doc__ or "")
