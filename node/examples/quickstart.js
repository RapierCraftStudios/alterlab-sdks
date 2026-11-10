"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const sdk_1 = require("alterlab");
async function main() {
    const client = new sdk_1.AlterLab({ apiKey: 'sk_test_...' });
    // Light scraping
    const result = await client.scrapeLight({ url: 'https://example.com' });
    console.log(`Content length: ${result.content.length}`);
    // Check usage
    const usage = await client.getUsage();
    console.log(`Credits remaining: ${usage.credits_available}`);
}
main().catch(console.error);
