import { AlterLab } from "alterlab";

async function main() {
  const client = new AlterLab({ apiKey: "sk_test_..." });

  // 1. Simple HTML scrape (fastest, ~1 credit)
  const result = await client.scrape({ url: "https://example.com" });
  console.log(`Content length: ${result.content.length} chars`);
  console.log(`Credits used: ${result.credits_used}`);

  // 2. JavaScript rendering for dynamic pages ("auto" renders only when the page needs it)
  const jsResult = await client.scrape({
    url: "https://example.com",
    render_js: "auto",
  });
  console.log(`JS-rendered: ${jsResult.content.length} chars`);

  // 3. Screenshot capture
  const screenshotResult = await client.scrape({
    url: "https://example.com",
    mode: "js",
    render_js: true,
    screenshot: true,
  });
  console.log(`Screenshot URL: ${screenshotResult.screenshot_url}`);

  // 4. Structured extraction with a profile
  const productResult = await client.scrape({
    url: "https://example.com/product",
    extraction_profile: "product",
  });
  console.log(`Extracted data:`, productResult.extracted_data);

  // 5. Custom JSON schema extraction
  const schemaResult = await client.scrape({
    url: "https://example.com/product",
    extraction_schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        price: { type: "number" },
      },
    },
  });
  console.log(`Schema result:`, schemaResult.extracted_data);
}

main().catch(console.error);
