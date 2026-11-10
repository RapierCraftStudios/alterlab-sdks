"""Basic SERP scraping examples using the AlterLab API.

Demonstrates how to:
- Execute a Google SERP scrape with ad extraction
- Parse organic results and ad placements
- Handle common errors (401, 402, 422, 503)
- Poll for async results
"""

import time
from typing import Any, Dict

import requests

API_KEY = "sk_test_..."
BASE_URL = "https://api.alterlab.io/v1/serp"


def serp_search(query: str, **kwargs: Any) -> Dict[str, Any]:
    """Execute a SERP scrape and return the full response.

    The /v1/serp endpoint uses browser-tier rendering (T4) to capture ads,
    organic results, and rich SERP data from Google. Cost: ~$0.004/request.

    Args:
        query: Search query string (max 500 chars).
        **kwargs: Additional SerpRequest fields (search_engine, device, country,
                  include_ads, brand_domain, resolve_redirects, etc.)

    Returns:
        Full SerpResponse dict with organic_results, ads, rich results, and cost.

    Raises:
        requests.HTTPError: On API errors (401, 402, 422, 503).
    """
    payload = {"query": query, **kwargs}

    response = requests.post(
        BASE_URL,
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def poll_serp_result(serp_id: str, max_wait: int = 60) -> Dict[str, Any]:
    """Poll for an async SERP result by serp_id.

    Use this when the initial request returns a 202 (async) or when using
    webhook_url and want to manually check status.

    Args:
        serp_id: The serp_id returned from the initial request.
        max_wait: Maximum seconds to poll before giving up.

    Returns:
        Full SerpResponse when complete.
    """
    url = f"{BASE_URL}/{serp_id}"
    start = time.time()

    while time.time() - start < max_wait:
        resp = requests.get(url, headers={"X-API-Key": API_KEY}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "completed":
            return data
        elif data.get("status") == "failed":
            raise RuntimeError(f"SERP scrape failed: {data.get('error')}")

        time.sleep(2)

    raise TimeoutError(f"SERP result not ready after {max_wait}s")


def handle_errors_example() -> None:
    """Demonstrate error handling for common SERP API errors."""
    try:
        result = serp_search("best crm software")
        print(f"Success! Found {result['organic_count']} organic results")

    except requests.HTTPError as e:
        status = e.response.status_code

        if status == 401:
            print("Authentication failed — check your API key")
        elif status == 402:
            err = e.response.json()
            topup_url = err.get("topup_url", "https://alterlab.io/dashboard/billing")
            print(f"Insufficient credits — add funds at: {topup_url}")
        elif status == 422:
            # Validation error — the request body has invalid fields
            errors = e.response.json().get("detail", [])
            print(f"Validation error: {errors}")
        elif status == 503:
            print("Service temporarily unavailable — retry after a few seconds")
        else:
            print(f"Unexpected error {status}: {e.response.text}")


def main() -> None:
    """Run basic SERP examples."""

    # 1. Simple Google SERP search with ads
    print("=== Basic SERP Search ===")
    result = serp_search("best project management tools 2026")
    print(f"Query: {result['query']}")
    print(f"Organic results: {result['organic_count']}")
    print(f"Ads found: {result['ads_count']}")
    print(f"Cost: ${result['cost_breakdown']['total_cost_usd']:.4f}")

    # Print first 3 organic results
    for i, item in enumerate(result["organic_results"][:3], 1):
        print(f"  {i}. {item['title']} — {item['url']}")

    # 2. SERP search with ads breakdown by placement
    print("\n=== Ad Placements ===")
    result = serp_search("buy running shoes online", include_ads=True)
    placements = result.get("ads_by_placement", {})
    print(f"Top ads: {placements.get('top', 0)}")
    print(f"Bottom ads: {placements.get('bottom', 0)}")
    print(f"Shopping ads: {placements.get('shopping', 0)}")

    for ad in result["ads"][:3]:
        print(f"  [{ad['placement']}] {ad['headline']} — {ad['display_url']}")

    # 3. Mobile SERP (different ad layout)
    print("\n=== Mobile SERP ===")
    result = serp_search("pizza delivery near me", device="mobile", country="US")
    print(f"Mobile organic results: {result['organic_count']}")
    print(f"Mobile ads: {result['ads_count']}")
    if result.get("local_results"):
        print(f"Local pack results: {len(result['local_results'])}")

    # 4. SERP without ads (faster, organic only)
    print("\n=== Organic Only (no ads) ===")
    result = serp_search("python asyncio tutorial", include_ads=False)
    print(f"Organic results: {result['organic_count']}")
    print(f"Ads: {result['ads_count']} (should be 0)")

    # 5. Error handling
    print("\n=== Error Handling ===")
    handle_errors_example()


if __name__ == "__main__":
    main()
