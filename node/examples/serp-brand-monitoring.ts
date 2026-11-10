/**
 * Brand monitoring examples using the AlterLab SERP API.
 *
 * Demonstrates:
 * - Detecting competitor ads on your brand keywords
 * - Classifying ads as brand vs. competitor
 * - Tracking ad positions and extensions
 * - Generating brand presence reports
 */

const API_KEY = "sk_test_...";
const BASE_URL = "https://api.alterlab.io/v1/serp";

// Types imported from serp-basic.ts (duplicated here for standalone use)
interface SerpAdResult {
  position: number;
  placement: "top" | "bottom" | "sidebar" | "shopping";
  ad_type: string;
  headline: string;
  display_url: string;
  landing_url?: string;
  advertiser_name?: string;
  extensions: { type: string; text: string; url?: string }[];
  is_brand_ad?: boolean;
}

interface SerpOrganicResult {
  position: number;
  title: string;
  url: string;
  snippet?: string;
}

interface SerpResponse {
  serp_id: string;
  query: string;
  organic_results: SerpOrganicResult[];
  organic_count: number;
  ads: SerpAdResult[];
  ads_count: number;
  ads_by_placement: Record<string, number>;
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
// Brand monitoring functions
// ---------------------------------------------------------------------------

interface CompetitorAd {
  position: number;
  placement: string;
  headline: string;
  displayUrl: string;
  landingUrl?: string;
  advertiser?: string;
  extensions: string[];
}

async function findCompetitorAds(
  query: string,
  brandDomain: string,
): Promise<CompetitorAd[]> {
  const result = await serpSearch({
    query,
    include_ads: true,
    brand_domain: brandDomain,
    resolve_redirects: true,
  });

  return result.ads
    .filter((ad) => ad.is_brand_ad === false)
    .map((ad) => ({
      position: ad.position,
      placement: ad.placement,
      headline: ad.headline,
      displayUrl: ad.display_url,
      landingUrl: ad.landing_url ?? undefined,
      advertiser: ad.advertiser_name ?? undefined,
      extensions: ad.extensions.map((ext) => ext.type),
    }));
}

interface KeywordReport {
  brandAdPresent: boolean;
  brandAdPosition: number | null;
  competitorAdCount: number;
  competitorAdvertisers: string[];
  organicRank: number | null;
  totalAds: number;
}

interface BrandPresenceReport {
  brandDomain: string;
  keywords: Record<string, KeywordReport>;
  summary: {
    totalKeywords: number;
    brandAdPresent: number;
    avgCompetitorCount: number;
    organicPresence: number;
  };
}

async function brandPresenceReport(
  brandDomain: string,
  keywords: string[],
): Promise<BrandPresenceReport> {
  const report: BrandPresenceReport = {
    brandDomain,
    keywords: {},
    summary: {
      totalKeywords: keywords.length,
      brandAdPresent: 0,
      avgCompetitorCount: 0,
      organicPresence: 0,
    },
  };

  let totalCompetitors = 0;

  for (const keyword of keywords) {
    const result = await serpSearch({
      query: keyword,
      include_ads: true,
      brand_domain: brandDomain,
    });

    const brandAds = result.ads.filter((ad) => ad.is_brand_ad === true);
    const competitorAds = result.ads.filter((ad) => ad.is_brand_ad === false);

    const organicRank =
      result.organic_results.findIndex((item) =>
        item.url.includes(brandDomain),
      ) + 1 || null;

    report.keywords[keyword] = {
      brandAdPresent: brandAds.length > 0,
      brandAdPosition: brandAds[0]?.position ?? null,
      competitorAdCount: competitorAds.length,
      competitorAdvertisers: competitorAds
        .slice(0, 5)
        .map((ad) => ad.advertiser_name || ad.display_url),
      organicRank,
      totalAds: result.ads_count,
    };

    totalCompetitors += competitorAds.length;
    if (brandAds.length > 0) report.summary.brandAdPresent++;
    if (organicRank) report.summary.organicPresence++;
  }

  report.summary.avgCompetitorCount = totalCompetitors / keywords.length;
  return report;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const brandDomain = "wayfair.com";

  // 1. Find competitor ads on brand keywords
  console.log("=== Competitor Ads on Brand Keywords ===");
  const competitors = await findCompetitorAds("wayfair furniture", brandDomain);
  console.log(
    `Found ${competitors.length} competitor ads on 'wayfair furniture':`,
  );
  for (const comp of competitors) {
    console.log(`  Position ${comp.position}: ${comp.headline}`);
    console.log(`    Display: ${comp.displayUrl}`);
    if (comp.landingUrl) console.log(`    Landing: ${comp.landingUrl}`);
    if (comp.advertiser) console.log(`    Advertiser: ${comp.advertiser}`);
    console.log();
  }

  // 2. Full brand presence report
  console.log("=== Brand Presence Report ===");
  const keywords = [
    "wayfair",
    "wayfair couches",
    "buy furniture online",
    "affordable home decor",
    "wayfair reviews",
  ];
  const report = await brandPresenceReport(brandDomain, keywords);

  console.log(`Brand: ${report.brandDomain}`);
  console.log(`Keywords monitored: ${report.summary.totalKeywords}`);
  console.log(
    `Brand ad present: ${report.summary.brandAdPresent}/${report.summary.totalKeywords}`,
  );
  console.log(
    `Organic presence: ${report.summary.organicPresence}/${report.summary.totalKeywords}`,
  );
  console.log(
    `Avg competitor ads: ${report.summary.avgCompetitorCount.toFixed(1)}`,
  );

  console.log("\nPer-keyword breakdown:");
  for (const [kw, data] of Object.entries(report.keywords)) {
    const status = data.brandAdPresent ? "Ad" : "No ad";
    const organic = data.organicRank
      ? `Rank #${data.organicRank}`
      : "Not ranked";
    console.log(
      `  [${status}] '${kw}' — ${data.competitorAdCount} competitors, ${organic}`,
    );
  }
}

main().catch(console.error);
