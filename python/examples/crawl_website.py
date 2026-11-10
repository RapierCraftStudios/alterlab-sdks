"""Website crawling examples using the AlterLab Python SDK."""

import asyncio

from alterlab import AlterLab


async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        # 1. Start a crawl (returns immediately)
        crawl = await client.crawl(
            "https://example.com",
            max_pages=100,
            max_depth=2,
            formats=["markdown"],
        )
        print(f"Crawl ID: {crawl['crawl_id']}")
        print(f"Estimated pages: {crawl['estimated_pages']}")

        # 2. Poll crawl progress
        status = await client.get_crawl(crawl["crawl_id"])
        print(f"Status: {status['status']}")
        print(f"Progress: {status['completed']}/{status['total']}")

        # 3. Get results when done
        status = await client.get_crawl(crawl["crawl_id"], include_results=True)
        for page in status.get("pages", []):
            print(f"  {page['url']}: {page['status']}")

        # 4. Or use crawl_and_wait for a blocking call
        results = await client.crawl_and_wait(
            "https://example.com",
            max_pages=50,
            include_patterns=["/blog/*"],
            exclude_patterns=["/blog/drafts/*"],
            formats=["markdown"],
            poll_timeout=300.0,
        )
        print(f"Crawl complete: {results['completed']} pages scraped")
        print(f"Credits used: {results['credits_debited']}")

        # 5. Cancel a crawl (refunds unprocessed pages)
        crawl = await client.crawl("https://example.com", max_pages=1000)
        cancel = await client.cancel_crawl(crawl["crawl_id"])
        print(f"Cancelled {cancel['cancelled_jobs']} jobs")
        print(f"Refunded {cancel['credits_refunded']} credits")


if __name__ == "__main__":
    asyncio.run(main())
