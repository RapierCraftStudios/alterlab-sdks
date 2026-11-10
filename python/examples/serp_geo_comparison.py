"""Geo-targeted SERP comparison examples using the AlterLab API.

Demonstrates how to:
- Compare SERP results across different countries
- Analyze regional ad differences
- Detect geo-specific ad targeting strategies
- Compare mobile vs. desktop ad placements per region
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


def compare_geo_serps(
    query: str,
    countries: List[str],
    include_ads: bool = True,
) -> Dict[str, Any]:
    """Compare SERP results for the same query across multiple countries.

    Useful for understanding how ad targeting differs by region and which
    advertisers are active in each market.

    Args:
        query: Search query to compare across geos.
        countries: List of ISO 3166-1 alpha-2 country codes (e.g. ["US", "GB", "DE"]).
        include_ads: Whether to extract ads (default True).

    Returns:
        Dict with per-country SERP data and comparison metrics.
    """
    results = {}

    for country in countries:
        result = serp_search(
            query,
            country=country,
            include_ads=include_ads,
        )
        results[country] = {
            "organic_count": result["organic_count"],
            "ads_count": result["ads_count"],
            "ads_by_placement": result.get("ads_by_placement", {}),
            "top_organic": [
                {"title": r["title"], "url": r["url"]}
                for r in result["organic_results"][:5]
            ],
            "advertisers": [
                {
                    "headline": ad["headline"],
                    "display_url": ad["display_url"],
                    "placement": ad["placement"],
                    "position": ad["position"],
                }
                for ad in result["ads"]
            ],
            "has_local_results": len(result.get("local_results", [])) > 0,
            "has_shopping": result.get("ads_by_placement", {}).get("shopping", 0) > 0,
            "featured_snippet": result.get("featured_snippet") is not None,
            "cost_usd": result.get("cost_breakdown", {}).get("total_cost_usd"),
        }

    return {
        "query": query,
        "countries": results,
        "comparison": _build_comparison(results),
    }


def _build_comparison(results: Dict[str, Any]) -> Dict[str, Any]:
    """Build comparison metrics from per-country results."""
    countries = list(results.keys())

    # Find advertisers that appear in multiple countries
    advertiser_sets = {
        country: {ad["display_url"] for ad in data["advertisers"]}
        for country, data in results.items()
    }

    # Advertisers present in all countries
    if advertiser_sets:
        global_advertisers = set.intersection(*advertiser_sets.values())
    else:
        global_advertisers = set()

    # Advertisers unique to one country
    local_only = {}
    for country, ads in advertiser_sets.items():
        others = (
            set.union(*(s for c, s in advertiser_sets.items() if c != country))
            if len(advertiser_sets) > 1
            else set()
        )
        local_only[country] = ads - others

    return {
        "global_advertisers": list(global_advertisers),
        "local_only_advertisers": {k: list(v) for k, v in local_only.items()},
        "ad_density": {country: data["ads_count"] for country, data in results.items()},
        "shopping_presence": {
            country: data["has_shopping"] for country, data in results.items()
        },
    }


def device_comparison(
    query: str,
    country: str = "US",
) -> Dict[str, Any]:
    """Compare desktop vs. mobile SERP for the same query and country.

    Mobile SERPs often have different ad layouts and fewer ad slots.

    Args:
        query: Search query.
        country: Country code for geo-targeting.

    Returns:
        Comparison dict with desktop vs. mobile metrics.
    """
    desktop = serp_search(query, country=country, device="desktop", include_ads=True)
    mobile = serp_search(query, country=country, device="mobile", include_ads=True)

    return {
        "query": query,
        "country": country,
        "desktop": {
            "ads_count": desktop["ads_count"],
            "organic_count": desktop["organic_count"],
            "ads_by_placement": desktop.get("ads_by_placement", {}),
            "has_shopping": desktop.get("ads_by_placement", {}).get("shopping", 0) > 0,
        },
        "mobile": {
            "ads_count": mobile["ads_count"],
            "organic_count": mobile["organic_count"],
            "ads_by_placement": mobile.get("ads_by_placement", {}),
            "has_shopping": mobile.get("ads_by_placement", {}).get("shopping", 0) > 0,
        },
    }


def main() -> None:
    """Run geo-comparison examples."""

    # 1. Compare SERPs across US, UK, and Germany
    print("=== Geo-Comparison: 'crm software' ===")
    comparison = compare_geo_serps(
        "crm software",
        countries=["US", "GB", "DE"],
    )

    for country, data in comparison["countries"].items():
        print(
            f"\n  [{country}] Organic: {data['organic_count']}, Ads: {data['ads_count']}"
        )
        print(f"    Placements: {data['ads_by_placement']}")
        print(f"    Shopping: {'Yes' if data['has_shopping'] else 'No'}")
        print(f"    Featured snippet: {'Yes' if data['featured_snippet'] else 'No'}")
        if data["advertisers"]:
            print(f"    Top advertiser: {data['advertisers'][0]['headline']}")

    print("\n  Global advertisers (appear in all geos):")
    for adv in comparison["comparison"]["global_advertisers"]:
        print(f"    - {adv}")

    print("\n  Local-only advertisers:")
    for country, advs in comparison["comparison"]["local_only_advertisers"].items():
        if advs:
            print(f"    [{country}]: {', '.join(advs[:3])}")

    # 2. Desktop vs. Mobile comparison
    print("\n=== Device Comparison: 'buy laptop online' (US) ===")
    device_comp = device_comparison("buy laptop online", country="US")

    print(
        f"  Desktop — Ads: {device_comp['desktop']['ads_count']}, "
        f"Organic: {device_comp['desktop']['organic_count']}"
    )
    print(f"    Placements: {device_comp['desktop']['ads_by_placement']}")

    print(
        f"  Mobile  — Ads: {device_comp['mobile']['ads_count']}, "
        f"Organic: {device_comp['mobile']['organic_count']}"
    )
    print(f"    Placements: {device_comp['mobile']['ads_by_placement']}")

    # 3. Multi-language comparison for the same country
    print("\n=== Language Comparison: 'web hosting' in Switzerland ===")
    for lang in ["de", "fr", "it"]:
        result = serp_search(
            "web hosting", country="CH", language=lang, include_ads=True
        )
        print(
            f"  [{lang}] Ads: {result['ads_count']}, Organic: {result['organic_count']}"
        )
        if result["ads"]:
            print(f"    Top ad: {result['ads'][0]['headline']}")


if __name__ == "__main__":
    main()
