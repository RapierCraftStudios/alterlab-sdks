/**
 * Geo-targeted SERP comparison examples using the AlterLab API.
 *
 * Demonstrates:
 * - Comparing SERP results across different countries
 * - Analyzing regional ad differences
 * - Detecting geo-specific ad targeting
 * - Desktop vs. mobile comparisons per region
 */

const API_KEY = "sk_test_...";
const BASE_URL = "https://api.alterlab.io/v1/serp";

// Minimal types for standalone use
interface SerpResponse {
  serp_id: string;
  query: string;
  organic_results: { position: number; title: string; url: string }[];
  organic_count: number;
  ads: {
    position: number;
    placement: string;
    headline: string;
    display_url: string;
  }[];
  ads_count: number;
  ads_by_placement: Record<string, number>;
  featured_snippet?: { answer: string; source_url: string };
  local_results: any[];
  cost_breakdown?: { total_cost_usd: number };
  engines_attempted: string[];
}

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

async function serpSearch(payload: Record<string, any>): Promise<SerpResponse> {
  const response = await fetch(BASE_URL, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`SERP API error ${response.status}: ${body}`);
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Geo-comparison functions
// ---------------------------------------------------------------------------

interface GeoCountryData {
  organicCount: number;
  adsCount: number;
  adsByPlacement: Record<string, number>;
  topOrganic: { title: string; url: string }[];
  advertisers: { headline: string; displayUrl: string; placement: string }[];
  hasShopping: boolean;
  hasFeaturedSnippet: boolean;
  costUsd?: number;
}

interface GeoComparison {
  query: string;
  countries: Record<string, GeoCountryData>;
  comparison: {
    globalAdvertisers: string[];
    localOnlyAdvertisers: Record<string, string[]>;
    adDensity: Record<string, number>;
  };
}

async function compareGeoSerps(
  query: string,
  countries: string[],
): Promise<GeoComparison> {
  const results: Record<string, GeoCountryData> = {};

  for (const country of countries) {
    const result = await serpSearch({
      query,
      country,
      include_ads: true,
    });

    results[country] = {
      organicCount: result.organic_count,
      adsCount: result.ads_count,
      adsByPlacement: result.ads_by_placement,
      topOrganic: result.organic_results.slice(0, 5).map((r) => ({
        title: r.title,
        url: r.url,
      })),
      advertisers: result.ads.map((ad) => ({
        headline: ad.headline,
        displayUrl: ad.display_url,
        placement: ad.placement,
      })),
      hasShopping: (result.ads_by_placement.shopping || 0) > 0,
      hasFeaturedSnippet: result.featured_snippet != null,
      costUsd: result.cost_breakdown?.total_cost_usd,
    };
  }

  // Build comparison metrics
  const advertiserSets: Record<string, Set<string>> = {};
  for (const [country, data] of Object.entries(results)) {
    advertiserSets[country] = new Set(
      data.advertisers.map((a) => a.displayUrl),
    );
  }

  const allSets = Object.values(advertiserSets);
  const globalAdvertisers =
    allSets.length > 0
      ? [...allSets[0]].filter((url) => allSets.every((s) => s.has(url)))
      : [];

  const localOnly: Record<string, string[]> = {};
  for (const [country, ads] of Object.entries(advertiserSets)) {
    const otherAds = new Set(
      Object.entries(advertiserSets)
        .filter(([c]) => c !== country)
        .flatMap(([, s]) => [...s]),
    );
    localOnly[country] = [...ads].filter((url) => !otherAds.has(url));
  }

  return {
    query,
    countries: results,
    comparison: {
      globalAdvertisers,
      localOnlyAdvertisers: localOnly,
      adDensity: Object.fromEntries(
        Object.entries(results).map(([c, d]) => [c, d.adsCount]),
      ),
    },
  };
}

interface DeviceComparison {
  query: string;
  country: string;
  desktop: {
    adsCount: number;
    organicCount: number;
    adsByPlacement: Record<string, number>;
  };
  mobile: {
    adsCount: number;
    organicCount: number;
    adsByPlacement: Record<string, number>;
  };
}

async function compareDevices(
  query: string,
  country: string = "US",
): Promise<DeviceComparison> {
  const [desktop, mobile] = await Promise.all([
    serpSearch({ query, country, device: "desktop", include_ads: true }),
    serpSearch({ query, country, device: "mobile", include_ads: true }),
  ]);

  return {
    query,
    country,
    desktop: {
      adsCount: desktop.ads_count,
      organicCount: desktop.organic_count,
      adsByPlacement: desktop.ads_by_placement,
    },
    mobile: {
      adsCount: mobile.ads_count,
      organicCount: mobile.organic_count,
      adsByPlacement: mobile.ads_by_placement,
    },
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  // 1. Compare SERPs across US, UK, and Germany
  console.log("=== Geo-Comparison: 'crm software' ===");
  const comparison = await compareGeoSerps("crm software", ["US", "GB", "DE"]);

  for (const [country, data] of Object.entries(comparison.countries)) {
    console.log(
      `\n  [${country}] Organic: ${data.organicCount}, Ads: ${data.adsCount}`,
    );
    console.log(`    Placements: ${JSON.stringify(data.adsByPlacement)}`);
    console.log(`    Shopping: ${data.hasShopping ? "Yes" : "No"}`);
    console.log(
      `    Featured snippet: ${data.hasFeaturedSnippet ? "Yes" : "No"}`,
    );
    if (data.advertisers.length > 0) {
      console.log(`    Top advertiser: ${data.advertisers[0].headline}`);
    }
  }

  console.log("\n  Global advertisers (appear in all geos):");
  for (const adv of comparison.comparison.globalAdvertisers) {
    console.log(`    - ${adv}`);
  }

  console.log("\n  Local-only advertisers:");
  for (const [country, advs] of Object.entries(
    comparison.comparison.localOnlyAdvertisers,
  )) {
    if (advs.length > 0) {
      console.log(`    [${country}]: ${advs.slice(0, 3).join(", ")}`);
    }
  }

  // 2. Desktop vs. Mobile comparison
  console.log("\n=== Device Comparison: 'buy laptop online' (US) ===");
  const deviceComp = await compareDevices("buy laptop online", "US");
  console.log(
    `  Desktop — Ads: ${deviceComp.desktop.adsCount}, Organic: ${deviceComp.desktop.organicCount}`,
  );
  console.log(
    `    Placements: ${JSON.stringify(deviceComp.desktop.adsByPlacement)}`,
  );
  console.log(
    `  Mobile  — Ads: ${deviceComp.mobile.adsCount}, Organic: ${deviceComp.mobile.organicCount}`,
  );
  console.log(
    `    Placements: ${JSON.stringify(deviceComp.mobile.adsByPlacement)}`,
  );

  // 3. Multi-language comparison
  console.log("\n=== Language Comparison: 'web hosting' in Switzerland ===");
  for (const lang of ["de", "fr", "it"]) {
    const result = await serpSearch({
      query: "web hosting",
      country: "CH",
      language: lang,
      include_ads: true,
    });
    console.log(
      `  [${lang}] Ads: ${result.ads_count}, Organic: ${result.organic_count}`,
    );
    if (result.ads.length > 0) {
      console.log(`    Top ad: ${result.ads[0].headline}`);
    }
  }
}

main().catch(console.error);
