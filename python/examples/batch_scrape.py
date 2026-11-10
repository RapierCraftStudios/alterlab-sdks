"""Batch scraping examples using the AlterLab Python SDK."""

import asyncio

from alterlab import AlterLab


async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        # 1. Submit a batch of URLs
        batch = await client.batch_scrape(
            [
                {"url": "https://example.com/page1", "mode": "html"},
                {"url": "https://example.com/page2", "mode": "html"},
                {"url": "https://example.com/page3", "mode": "js"},
            ],
            webhook_url="https://myapp.com/webhook",  # optional
        )
        print(f"Batch ID: {batch['batch_id']}")
        print(f"Jobs: {len(batch['job_ids'])}")

        # 2. Wait for all jobs to complete
        results = []
        for job_id in batch["job_ids"]:
            result = await client.wait_for_job(job_id, poll_timeout=60.0)
            results.append(result)
            print(f"  Job {job_id}: done")

        total_credits = sum(r["billing"]["total_credits"] for r in results)
        print(f"Total credits: {total_credits}")

        # 3. Or check status without waiting
        for job_id in batch["job_ids"]:
            status = await client.get_job_status(job_id)
            print(f"  Job {job_id}: {status['status']}")


if __name__ == "__main__":
    asyncio.run(main())
