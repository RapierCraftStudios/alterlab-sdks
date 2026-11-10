"""Basic scraping examples using the AlterLab Python SDK."""

import asyncio

from alterlab import AlterLab, AdvancedOptions


async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        # 1. Simple HTML scrape (fastest, ~1 credit)
        result = await client.scrape("https://example.com")
        print(f"Content length: {len(result['content'])} chars")
        print(f"Credits used: {result['billing']['total_credits']}")

        # 2. JavaScript rendering for dynamic pages
        result = await client.scrape("https://example.com", mode="js")
        print(f"JS-rendered content: {len(result['content'])} chars")

        # 3. Get markdown output
        result = await client.scrape(
            "https://example.com",
            formats=["markdown", "text"],
        )
        print(f"Markdown: {result['filtered_content']['markdown'][:200]}")

        # 4. Screenshot capture
        result = await client.scrape(
            "https://example.com",
            mode="js",
            advanced=AdvancedOptions(render_js=True, screenshot=True),
        )
        print(f"Screenshot URL: {result.get('screenshot_url')}")


if __name__ == "__main__":
    asyncio.run(main())
