import { AlterLab } from "alterlab";

async function main() {
  const client = new AlterLab({ apiKey: "sk_test_..." });

  // 1. Estimate cost before scraping
  const estimate = await client.estimateCost({
    url: "https://example.com",
    mode: "js",
    advanced: { render_js: true, screenshot: true },
  });
  console.log(`Estimated credits: ${estimate.estimated_credits}`);
  console.log(`Max possible: ${estimate.max_possible_credits}`);
  console.log(`Confidence: ${estimate.confidence}`);
  console.log(`Reasoning: ${estimate.reasoning}`);

  // Only scrape if cost is acceptable
  if (estimate.estimated_credits <= 10) {
    const result = await client.scrape({
      url: "https://example.com",
      mode: "js",
      render_js: true,
      screenshot: true,
    });
    console.log(`Actual credits: ${result.credits_used}`);
  }

  // 2. Scrape with cost limits
  const result = await client.scrape({
    url: "https://example.com",
    max_credits: 5,
    max_tier: "2",
  });
  console.log(`Credits used: ${result.credits_used}`);

  // 3. Check credit balance
  const usage = await client.getUsage();
  console.log(`Balance: ${usage.balance_microcents} microcents`);
  console.log(`Account tier: ${usage.account_tier}`);
  console.log(`Entitlement source: ${usage.entitlement_source}`);
}

main().catch(console.error);
