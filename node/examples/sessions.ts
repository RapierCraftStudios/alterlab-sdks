/**
 * AlterLab SDK Session & Cookie Examples
 *
 * Demonstrates authenticated scraping using stored sessions and inline cookies.
 */

import { AlterLab } from "alterlab";

async function exampleInlineCookies() {
  console.log("\n" + "=".repeat(60));
  console.log("Example 1: Inline Cookies (One-off)");
  console.log("=".repeat(60));

  const client = new AlterLab({ apiKey: "sk_test_..." });

  // Pass cookies directly — not stored, just used for this request
  const result = await client.scrape({
    url: "https://amazon.com/dp/B0XXXXX",
    cookies: {
      "session-id": "abc123",
      "session-token": "xyz789",
      "ubid-main": "131-1234567-1234567",
    },
  });

  console.log(`Content length: ${result.content.length}`);
  console.log(`BYOS applied: ${result.byos_applied ?? false}`);
}

async function exampleSessionCrud() {
  console.log("\n" + "=".repeat(60));
  console.log("Example 2: Session CRUD");
  console.log("=".repeat(60));

  const client = new AlterLab({ apiKey: "sk_test_..." });

  // Create a session
  const session = await client.sessions.create({
    name: "My Amazon Prime",
    domain: "amazon.com",
    cookies: {
      "session-id": "abc123",
      "session-token": "xyz789",
    },
    notes: "Personal Prime account for product scraping",
  });
  console.log(`Created session: ${session.id}`);
  console.log(`  Name: ${session.name}`);
  console.log(`  Domain: ${session.domain}`);
  console.log(`  Cookie names: ${session.cookie_names.join(", ")}`);
  console.log(`  Status: ${session.status}`);

  // List all sessions
  const listResult = await client.sessions.list();
  console.log(`\nTotal sessions: ${listResult.total}`);
  for (const s of listResult.sessions) {
    console.log(`  - ${s.name} (${s.domain}) [${s.status}]`);
  }

  // Get a specific session
  const fetched = await client.sessions.get(session.id);
  console.log(`\nFetched session: ${fetched.name}`);

  // Update session name
  const updated = await client.sessions.update(session.id, {
    name: "Amazon Prime - Production",
    notes: "Updated for production use",
  });
  console.log(`Updated name: ${updated.name}`);

  // Delete when done
  await client.sessions.delete(session.id);
  console.log("Session deleted.");
}

async function exampleSessionValidation() {
  console.log("\n" + "=".repeat(60));
  console.log("Example 3: Session Validation");
  console.log("=".repeat(60));

  const client = new AlterLab({ apiKey: "sk_test_..." });

  const session = await client.sessions.create({
    name: "Target Session",
    domain: "target.com",
    cookies: { session_token: "abc123" },
  });

  // Validate the session
  const validation = await client.sessions.validate(session.id);
  console.log(`Valid: ${validation.is_valid}`);
  console.log(`Confidence: ${validation.confidence}%`);
  console.log(`Details: ${validation.details}`);
  if (validation.detected_user) {
    console.log(`Detected user: ${validation.detected_user}`);
  }
  if (validation.cookies_expiring_soon) {
    console.log("Warning: Some cookies are expiring soon!");
  }

  await client.sessions.delete(session.id);
}

async function exampleCookieRotation() {
  console.log("\n" + "=".repeat(60));
  console.log("Example 4: Cookie Rotation (Refresh)");
  console.log("=".repeat(60));

  const client = new AlterLab({ apiKey: "sk_test_..." });

  const session = await client.sessions.create({
    name: "Rotating Session",
    domain: "example.com",
    cookies: { auth: "old-token-123" },
  });
  console.log(`Original cookie names: ${session.cookie_names.join(", ")}`);

  // Rotate cookies
  const refreshed = await client.sessions.refresh(session.id, {
    cookies: { auth: "new-token-456", refresh: "refresh-789" },
  });
  console.log(`Refreshed cookie names: ${refreshed.cookie_names.join(", ")}`);
  console.log(`Status after refresh: ${refreshed.status}`);

  await client.sessions.delete(session.id);
}

async function exampleScrapeWithSession() {
  console.log("\n" + "=".repeat(60));
  console.log("Example 5: Scrape with Stored Session");
  console.log("=".repeat(60));

  const client = new AlterLab({ apiKey: "sk_test_..." });

  const session = await client.sessions.create({
    name: "Amazon Scraping Session",
    domain: "amazon.com",
    cookies: {
      "session-id": "abc123",
      "session-token": "xyz789",
    },
  });

  // Scrape using the stored session
  const result = await client.scrape({
    url: "https://amazon.com/dp/B0XXXXX",
    sessionId: session.id,
  });
  console.log(`Content length: ${result.content.length}`);
  console.log(`BYOS applied: ${result.byos_applied ?? false}`);

  await client.sessions.delete(session.id);
}

async function main() {
  console.log("=".repeat(60));
  console.log("AlterLab Node SDK - Session & Cookie Examples");
  console.log("=".repeat(60));

  await exampleInlineCookies();
  await exampleSessionCrud();
  await exampleSessionValidation();
  await exampleCookieRotation();
  await exampleScrapeWithSession();

  console.log("\n" + "=".repeat(60));
  console.log("All session examples completed!");
  console.log("=".repeat(60));
}

main().catch(console.error);
