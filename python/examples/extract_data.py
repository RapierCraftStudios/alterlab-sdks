"""Structured data extraction examples using the AlterLab Python SDK."""

import asyncio

from alterlab import AlterLab


async def main():
    async with AlterLab(api_key="sk_test_...") as client:
        # 1. Use a pre-built extraction profile
        result = await client.scrape(
            "https://example.com/product",
            extraction_profile="product",
        )
        data = result.get("structured_content", {})
        print(f"Product: {data.get('name')}")
        print(f"Price: {data.get('price')}")

        # 2. Custom JSON Schema extraction
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "price": {"type": "number"},
                "currency": {"type": "string"},
                "in_stock": {"type": "boolean"},
            },
            "required": ["title", "price"],
        }
        result = await client.scrape(
            "https://example.com/product",
            extraction_schema=schema,
        )
        print(f"Extracted: {result.get('structured_content')}")

        # 3. Natural language extraction prompt
        result = await client.scrape(
            "https://example.com/article",
            extraction_prompt="Extract the article title, author, and publication date",
        )
        print(f"Extracted: {result.get('structured_content')}")

        # 4. Extraction with evidence (provenance tracking)
        result = await client.scrape(
            "https://example.com/product",
            extraction_profile="product",
            evidence=True,
        )
        print(f"Data: {result.get('structured_content')}")
        print(f"Method: {result.get('extraction_method')}")

        # Available profiles: auto, product, article, job_posting, faq, recipe, event


if __name__ == "__main__":
    asyncio.run(main())
