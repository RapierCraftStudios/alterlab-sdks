import { AlterLab } from "alterlab";

async function main() {
  const client = new AlterLab({ apiKey: "sk_test_..." });

  // 1. Use a pre-built extraction profile
  const product = await client.scrape({
    url: "https://example.com/product",
    extraction_profile: "product",
  });
  console.log("Product data:", product.extracted_data);

  // 2. Custom JSON Schema extraction
  const schemaResult = await client.scrape({
    url: "https://example.com/product",
    extraction_schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        price: { type: "number" },
        currency: { type: "string" },
        in_stock: { type: "boolean" },
      },
      required: ["title", "price"],
    },
  });
  console.log("Schema extraction:", schemaResult.extracted_data);

  // 3. Natural language extraction prompt
  const promptResult = await client.scrape({
    url: "https://example.com/article",
    extraction_prompt:
      "Extract the article title, author, and publication date",
  });
  console.log("Prompt extraction:", promptResult.extracted_data);

  // Available profiles: auto, product, article, job_posting, faq, recipe, event
}

main().catch(console.error);
