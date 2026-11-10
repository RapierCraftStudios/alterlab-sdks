/**
 * #36949: 402 insufficient-balance errors surface `topup_url` and the active
 * welcome offer on `InsufficientFundsError` (still an AxiosError, status 402).
 */
import axios, { AxiosError } from "axios";
import MockAdapter from "axios-mock-adapter";
import { AlterLab, InsufficientFundsError } from "../src/index";

const OFFER = { expires_at: "2026-10-29T00:00:00+00:00", match_pct: 100 };

async function scrapeError(body: unknown): Promise<unknown> {
  const mock = new MockAdapter(axios);
  mock.onAny().reply(402, body);
  const client = new AlterLab({ apiKey: "sk_test_x", maxRetries: 1 });
  try {
    await client.scrape({ url: "https://example.com" });
  } catch (e) {
    return e;
  } finally {
    mock.restore();
  }
  throw new Error("expected scrape to throw");
}

describe("InsufficientFundsError (#36949)", () => {
  it("reads topup_url and welcome_offer from the API detail", async () => {
    const e = await scrapeError({
      detail: {
        error: "insufficient_credits",
        message: "Balance empty.",
        topup_url: "https://x/billing?quick_topup=1000&tl=t",
        welcome_offer: OFFER,
      },
    });
    expect(e).toBeInstanceOf(InsufficientFundsError);
    expect(e).toBeInstanceOf(AxiosError);
    const err = e as InsufficientFundsError;
    expect(err.response?.status).toBe(402);
    expect(err.topupUrl).toBe("https://x/billing?quick_topup=1000&tl=t");
    expect(err.welcomeOffer).toEqual(OFFER);
  });

  it("reads the Firecrawl-compat top-level shape", async () => {
    const e = (await scrapeError({
      success: false,
      error: "Balance empty.",
      topup_url: "https://x/t",
    })) as InsufficientFundsError;
    expect(e.topupUrl).toBe("https://x/t");
    expect(e.welcomeOffer).toBeNull();
  });

  it("stays null when the server sends no new fields", async () => {
    const e = (await scrapeError({ detail: "x" })) as InsufficientFundsError;
    expect(e.topupUrl).toBeNull();
    expect(e.welcomeOffer).toBeNull();
    expect(e.billingUrl).toBe("https://alterlab.io/dashboard/billing");
  });
});
