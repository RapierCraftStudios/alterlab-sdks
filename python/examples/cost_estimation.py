"""Cost estimation and cost control examples using the AlterLab Python SDK."""

import asyncio

from alterlab import AlterLab, AdvancedOptions, CostControls


async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        # 1. Estimate cost before scraping
        estimate = await client.estimate_cost(
            "https://example.com",
            mode="js",
            advanced=AdvancedOptions(render_js=True, screenshot=True),
        )
        print(f"Estimated credits: {estimate['estimated_credits']}")
        print(f"Max possible: {estimate['max_possible_credits']}")
        print(f"Confidence: {estimate['confidence']}")

        # Only scrape if cost is acceptable
        if estimate["estimated_credits"] <= 10:
            result = await client.scrape(
                "https://example.com",
                mode="js",
                advanced=AdvancedOptions(render_js=True, screenshot=True),
            )
            print(f"Actual credits: {result['billing']['total_credits']}")

        # 2. Set hard credit limits
        result = await client.scrape(
            "https://example.com",
            cost_controls=CostControls(
                max_credits=5,
                max_tier="2",
                fail_fast=True,
            ),
        )

        # 3. Optimize for cost (try cheaper tiers first)
        result = await client.scrape(
            "https://example.com",
            cost_controls=CostControls(prefer_cost=True),
        )

        # 4. Optimize for speed (skip to reliable tier)
        result = await client.scrape(
            "https://example.com",
            cost_controls=CostControls(prefer_speed=True),
        )

        # 5. Check credit balance
        usage = await client.get_usage()
        print(f"Balance: {usage['balance_microcents']} microcents")
        print(f"Account tier: {usage['account_tier']}")
        print(f"Entitlement source: {usage['entitlement_source']}")


if __name__ == "__main__":
    asyncio.run(main())
