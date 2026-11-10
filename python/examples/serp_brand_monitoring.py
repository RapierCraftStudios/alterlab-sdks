"""Brand monitoring examples using the AlterLab SERP API.

Demonstrates how to:
- Detect competitor ads on your brand keywords
- Classify ads as brand vs. competitor
- Track ad positions over time
- Monitor brand SERP presence with ad extensions analysis
"""

from typing import Any, Dict, List

import requests

API_KEY = "sk_test_..."
BASE_URL = "https://api.alterlab.io/v1/serp"


def serp_search(query: str, **kwargs: Any) -> Dict[str, Any]:
    """Execute a SERP scrape. See serp_basic.py for full docstring."""
    response = requests.post(
        BASE_URL,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json={"query": query, **kwargs},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def find_competitor_ads(query: str, brand_domain: str) -> List[Dict[str, Any]]:
    """Find competitor ads bidding on your brand keywords.

    Uses the brand_domain parameter to classify each ad — ads where the
    display URL does NOT match your brand are competitor ads.

    Args:
        query: Brand-related search query (e.g. "wayfair furniture").
        brand_domain: Your brand's domain (e.g. "wayfair.com").

    Returns:
        List of competitor ad dicts with position, headline, advertiser info.
    """
    result = serp_search(
        query,
        include_ads=True,
        brand_domain=brand_domain,
        resolve_redirects=True,  # Get actual landing URLs
    )

    competitors = []
    for ad in result["ads"]:
        if ad["is_brand_ad"] is False:
            competitors.append(
                {
                    "position": ad["position"],
                    "placement": ad["placement"],
                    "headline": ad["headline"],
                    "display_url": ad["display_url"],
                    "landing_url": ad["landing_url"],
                    "advertiser": ad.get("advertiser_name"),
                    "extensions": [ext["type"] for ext in ad.get("extensions", [])],
                }
            )

    return competitors


def brand_presence_report(brand_domain: str, keywords: List[str]) -> Dict[str, Any]:
    """Generate a brand SERP presence report across multiple keywords.

    For each keyword, checks:
    - Whether your brand ad appears (is_brand_ad=True)
    - Your brand ad position
    - Number of competitor ads
    - Whether you appear in organic results

    Args:
        brand_domain: Your brand's domain (e.g. "wayfair.com").
        keywords: List of brand keywords to monitor.

    Returns:
        Report dict with per-keyword metrics.
    """
    report: Dict[str, Any] = {
        "brand_domain": brand_domain,
        "keywords": {},
        "summary": {
            "total_keywords": len(keywords),
            "brand_ad_present": 0,
            "avg_competitor_count": 0.0,
            "organic_presence": 0,
        },
    }

    total_competitors = 0

    for keyword in keywords:
        result = serp_search(
            keyword,
            include_ads=True,
            brand_domain=brand_domain,
        )

        # Check brand ad presence
        brand_ads = [ad for ad in result["ads"] if ad["is_brand_ad"] is True]
        competitor_ads = [ad for ad in result["ads"] if ad["is_brand_ad"] is False]

        # Check organic presence
        organic_match = any(
            brand_domain in item.get("url", "") for item in result["organic_results"]
        )

        keyword_data = {
            "brand_ad_present": len(brand_ads) > 0,
            "brand_ad_position": brand_ads[0]["position"] if brand_ads else None,
            "competitor_ad_count": len(competitor_ads),
            "competitor_advertisers": [
                ad.get("advertiser_name", ad["display_url"])
                for ad in competitor_ads[:5]
            ],
            "organic_rank": next(
                (
                    i + 1
                    for i, item in enumerate(result["organic_results"])
                    if brand_domain in item.get("url", "")
                ),
                None,
            ),
            "total_ads": result["ads_count"],
        }

        report["keywords"][keyword] = keyword_data
        total_competitors += len(competitor_ads)

        if brand_ads:
            report["summary"]["brand_ad_present"] += 1
        if organic_match:
            report["summary"]["organic_presence"] += 1

    report["summary"]["avg_competitor_count"] = (
        total_competitors / len(keywords) if keywords else 0
    )

    return report


def main() -> None:
    """Run brand monitoring examples."""

    brand = "wayfair.com"

    # 1. Find competitors bidding on your brand name
    print("=== Competitor Ads on Brand Keywords ===")
    competitors = find_competitor_ads("wayfair furniture", brand)
    print(f"Found {len(competitors)} competitor ads on 'wayfair furniture':")
    for comp in competitors:
        print(f"  Position {comp['position']}: {comp['headline']}")
        print(f"    Display: {comp['display_url']}")
        print(f"    Landing: {comp['landing_url']}")
        if comp["advertiser"]:
            print(f"    Advertiser: {comp['advertiser']}")
        print()

    # 2. Full brand presence report across keywords
    print("=== Brand Presence Report ===")
    keywords = [
        "wayfair",
        "wayfair couches",
        "buy furniture online",
        "affordable home decor",
        "wayfair reviews",
    ]
    report = brand_presence_report(brand, keywords)

    summary = report["summary"]
    print(f"Brand: {report['brand_domain']}")
    print(f"Keywords monitored: {summary['total_keywords']}")
    print(
        f"Brand ad present: {summary['brand_ad_present']}/{summary['total_keywords']}"
    )
    print(
        f"Organic presence: {summary['organic_presence']}/{summary['total_keywords']}"
    )
    print(f"Avg competitor ads: {summary['avg_competitor_count']:.1f}")

    print("\nPer-keyword breakdown:")
    for kw, data in report["keywords"].items():
        status = "✓ Ad" if data["brand_ad_present"] else "✗ No ad"
        organic = (
            f"Rank #{data['organic_rank']}" if data["organic_rank"] else "Not ranked"
        )
        print(
            f"  [{status}] '{kw}' — {data['competitor_ad_count']} competitors, {organic}"
        )

    # 3. Ad extensions analysis (sitelinks, callouts, etc.)
    print("\n=== Ad Extensions Analysis ===")
    result = serp_search("wayfair", include_ads=True, brand_domain=brand)
    for ad in result["ads"]:
        if ad["extensions"]:
            label = "BRAND" if ad["is_brand_ad"] else "COMPETITOR"
            print(f"  [{label}] {ad['headline']}")
            for ext in ad["extensions"]:
                print(f"    - {ext['type']}: {ext['text']}")


if __name__ == "__main__":
    main()
