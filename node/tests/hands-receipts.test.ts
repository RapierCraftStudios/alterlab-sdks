import { readFileSync } from "fs";
import { join } from "path";
import { canonicalJson, verifyReceipt } from "../src/hands-receipts";

const data = JSON.parse(
  readFileSync(
    join(__dirname, "../../../tests/hands_conformance/fixtures/receipts.json"),
    "utf8",
  ),
);

describe("verifyReceipt", () => {
  it("verifies every fixture receipt, including retired keys", () => {
    expect(data.receipts.length).toBeGreaterThanOrEqual(6);
    for (const receipt of data.receipts) {
      const result = verifyReceipt(receipt, data.key_set);
      expect(result.valid).toBe(true);
    }
    expect(verifyReceipt(data.receipts[0], data.key_set).keyStatus).toBe(
      "retired",
    );
  });

  it("rejects tampered receipts", () => {
    for (const receipt of data.tampered) {
      expect(verifyReceipt(receipt, data.key_set).valid).toBe(false);
    }
  });

  it("reports the failing check", () => {
    const bundleEdit = JSON.parse(JSON.stringify(data.receipts[0]));
    bundleEdit.bundle.status = 418;
    expect(verifyReceipt(bundleEdit, data.key_set).reason).toBe(
      "bundle_hash_mismatch",
    );
    const siteEdit = { ...data.receipts[0], site: "other.test" };
    expect(verifyReceipt(siteEdit, data.key_set).reason).toBe(
      "envelope_mismatch:site",
    );
    const unknown = { ...data.receipts[0], key_version: "nope" };
    expect(verifyReceipt(unknown, data.key_set).reason).toBe("unknown_key");
  });

  it("marks legacy HMAC receipts as not offline verifiable", () => {
    const legacy = { ...data.receipts[0], alg: "hmac-sha256" };
    expect(verifyReceipt(legacy, data.key_set).reason).toBe(
      "not_offline_verifiable",
    );
  });

  it("never throws on a malformed receipt", () => {
    expect(verifyReceipt({ alg: "ed25519" }, data.key_set).valid).toBe(false);
  });
});

describe("canonicalJson", () => {
  it("matches the Python reference for shared samples", () => {
    for (const sample of data.canonical) {
      expect(canonicalJson(sample.value).toString("utf8")).toBe(
        sample.canonical,
      );
    }
  });
});
