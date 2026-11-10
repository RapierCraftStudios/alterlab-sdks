"""#39751: SDK docs mention the `revalidated` response field added by #39687."""

from alterlab import client


def test_scrape_docs_mention_revalidated():
    assert "revalidated" in (client.AlterLab.scrape.__doc__ or "")
