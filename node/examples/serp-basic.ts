/**
 * Basic SERP scraping examples using the AlterLab API.
 *
 * Demonstrates:
 * - Executing a Google SERP scrape with ad extraction
 * - Parsing organic results and ad placements
 * - Handling common errors (401, 402, 422, 503)
 * - Polling for async results
 */

const API_KEY = "sk_test_...";
const BASE_URL = "https://api.alterlab.io/v1/serp";

// ---------------------------------------------------------------------------
// Types (matching SerpResponse schema)
// ---------------------------------------------------------------------------

interface SerpAdExtension {
  type: string;
  text: string;
  url?: string;
}

interface SerpAdResult {
  position: number;
  placement: "top" | "bottom" | "sidebar" | "shopping";
  ad_type: "text" | "shopping" | "local" | "video" | "app";
  headline: string;
  headline_2?: string;
  headline_3?: string;
  description?: string;
  display_url: string;
  landing_url?: string;
  tracking_url?: string;
  advertiser_name?: string;
  extensions: SerpAdExtension[];
  is_brand_ad?: boolean;
  price?: string;
  merchant?: string;
  image_url?: string;
}

interface SerpOrganicResult {
  position: number;
  title: string;
  url: string;
  snippet?: string;
  sitelinks?: { title: string; url: string }[];
}

interface SerpCostBreakdown {
  base_cost_microcents: number;
  captcha_cost_microcents: number;
  total_cost_microcents: number;
  total_cost_usd: number;
}

interface SerpResponse {
  serp_id: string;
  query: string;
  search_engine: string;
  device: string;
  country?: string;
  language?: string;
  organic_results: SerpOrganicResult[];
  organic_count: number;
  ads: SerpAdResult[];
  ads_count: number;
  ads_by_placement: Record<string, number>;
  featured_snippet?: { answer: string; source_url: string };
  related_searches: string[];
  local_results: any[];
  cost_breakdown?: SerpCostBreakdown;
  latency_ms?: number;
  engines_attempted: string[];
}

interface SerpRequest {
  query: string;
  search_engine?: "google" | "bing";
  device?: "desktop" | "mobile";
  country?: string;
  city?: string;
  language?: string;
  num_results?: number;
  page?: number;
  include_ads?: boolean;
  brand_domain?: string;
  resolve_redirects?: boolean;
  solve_captchas?: boolean;
  session_id?: string;
  webhook_url?: string;
}

// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------

async function serpSearch(request: SerpRequest): Promise<SerpResponse> {
  const response = await fetch(BASE_URL, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new SerpApiError(response.status, body);
  }

  return response.json();
}

async function pollSerpResult(
  serpId: string,
  maxWaitMs: number = 60000,
): Promise<SerpResponse> {
  const start = Date.now();

  while (Date.now() - start < maxWaitMs) {
    const response = await fetch(`${BASE_URL}/${serpId}`, {
      headers: { "X-API-Key": API_KEY },
    });

    if (!response.ok) {
      throw new SerpApiError(response.status, await response.text());
    }

    const data = await response.json();

    if (data.status === "completed") {
      return data;
    } else if (data.status === "failed") {
      throw new Error(`SERP scrape failed: ${data.error}`);
    }

    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  throw new Error(`SERP result not ready after ${maxWaitMs}ms`);
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

class SerpApiError extends Error {
  constructor(
    public statusCode: number,
    public responseBody: string,
  ) {
    super(`SERP API error ${statusCode}: ${responseBody}`);
    this.name = "SerpApiError";
  }
}

function handleSerpError(error: unknown): void {
  if (error instanceof SerpApiError) {
    switch (error.statusCode) {
      case 401:
        console.error("Authentication failed — check your API key");
        break;
      case 402: {
        const errBody = (() => {
          try {
            return JSON.parse(error.responseBody);
          } catch {
            return {};
          }
        })();
        const topupUrl =
          errBody.topup_url ?? "https://alterlab.io/dashboard/billing";
        console.error(`Insufficient credits — add funds at: ${topupUrl}`);
        break;
      }
      case 422:
        console.error(`Validation error: ${error.responseBody}`);
        break;
      case 503:
        console.error(
          "Service temporarily unavailable — retry after a few seconds",
        );
        break;
      default:
        console.error(
          `Unexpected error ${error.statusCode}: ${error.responseBody}`,
        );
    }
  } else {
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Examples
// ---------------------------------------------------------------------------

async function main() {
  // 1. Simple Google SERP search with ads
  console.log("=== Basic SERP Search ===");
  try {
    const result = await serpSearch({
      query: "best project management tools 2026",
    });
    console.log(`Query: ${result.query}`);
    console.log(`Organic results: ${result.organic_count}`);
    console.log(`Ads found: ${result.ads_count}`);
    console.log(`Cost: $${result.cost_breakdown?.total_cost_usd.toFixed(4)}`);

    // Print first 3 organic results
    for (const item of result.organic_results.slice(0, 3)) {
      console.log(`  ${item.position}. ${item.title} — ${item.url}`);
    }
  } catch (error) {
    handleSerpError(error);
  }

  // 2. SERP search with ad placement breakdown
  console.log("\n=== Ad Placements ===");
  try {
    const result = await serpSearch({
      query: "buy running shoes online",
      include_ads: true,
    });
    const placements = result.ads_by_placement;
    console.log(`Top ads: ${placements.top || 0}`);
    console.log(`Bottom ads: ${placements.bottom || 0}`);
    console.log(`Shopping ads: ${placements.shopping || 0}`);

    for (const ad of result.ads.slice(0, 3)) {
      console.log(`  [${ad.placement}] ${ad.headline} — ${ad.display_url}`);
    }
  } catch (error) {
    handleSerpError(error);
  }

  // 3. Mobile SERP
  console.log("\n=== Mobile SERP ===");
  try {
    const result = await serpSearch({
      query: "pizza delivery near me",
      device: "mobile",
      country: "US",
    });
    console.log(`Mobile organic results: ${result.organic_count}`);
    console.log(`Mobile ads: ${result.ads_count}`);
    if (result.local_results.length > 0) {
      console.log(`Local pack results: ${result.local_results.length}`);
    }
  } catch (error) {
    handleSerpError(error);
  }

  // 4. Organic only (no ads, faster)
  console.log("\n=== Organic Only ===");
  try {
    const result = await serpSearch({
      query: "typescript generics tutorial",
      include_ads: false,
    });
    console.log(`Organic results: ${result.organic_count}`);
    console.log(`Ads: ${result.ads_count} (should be 0)`);
  } catch (error) {
    handleSerpError(error);
  }
}

main().catch(console.error);
