import { AlterLab } from "alterlab";

async function main() {
  const client = new AlterLab({ apiKey: "sk_test_..." });

  // 1. Start a crawl (returns immediately)
  const crawl = await client.crawl({
    url: "https://example.com",
    maxPages: 100,
    maxDepth: 2,
    includePatterns: ["/blog/*"],
    formats: ["markdown"],
  });
  console.log(`Crawl ID: ${crawl.crawl_id}`);
  console.log(`Estimated pages: ${crawl.estimated_pages}`);

  // 2. Poll crawl progress
  const status = await client.getCrawl(crawl.crawl_id);
  console.log(`Status: ${status.status}`);
  console.log(`Progress: ${status.completed}/${status.total}`);

  // 3. Get results with page data
  const withResults = await client.getCrawl(crawl.crawl_id, true);
  for (const page of withResults.pages ?? []) {
    console.log(`  ${page.url}: ${page.status}`);
  }

  // 4. Or use crawlAndWait for a blocking call
  const results = await client.crawlAndWait(
    {
      url: "https://example.com",
      maxPages: 50,
      formats: ["markdown"],
    },
    { pollTimeout: 300000 },
  );
  console.log(`Crawl complete: ${results.completed} pages`);
  console.log(`Credits used: ${results.credits_debited}`);

  // 5. Cancel a crawl (refunds unprocessed pages)
  const newCrawl = await client.crawl({
    url: "https://example.com",
    maxPages: 1000,
  });
  const cancel = await client.cancelCrawl(newCrawl.crawl_id);
  console.log(`Cancelled ${cancel.cancelled_jobs} jobs`);
  console.log(`Refunded ${cancel.credits_refunded} credits`);
}

main().catch(console.error);
