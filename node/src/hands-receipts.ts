/**
 * Offline verification of signed Hands receipts (#39829).
 *
 * A receipt is trusted when its Ed25519 signature over the canonical JSON of `signed` verifies under
 * the key named by `key_version` in the published key set (GET /api/v1/hands/receipt-keys), when
 * sha256(canonical(bundle)) equals `bundle_hash`, and when the signed envelope agrees with the
 * fields shown beside it. Uses Node's built-in crypto; nothing calls the network.
 *
 * Canonical JSON matches the Python reference: keys sorted, compact separators, every character
 * outside printable ASCII escaped as \uXXXX (lowercase hex).
 */

import { createHash, createPublicKey, verify } from "crypto";

export interface ReceiptKey {
  kid: string;
  alg: string;
  public_key: string;
  status: "active" | "retired";
}

export interface ReceiptKeySet {
  schema_version: number;
  keys: ReceiptKey[];
}

export interface ReceiptVerification {
  valid: boolean;
  reason?: string;
  keyStatus?: "active" | "retired";
}

// A signed Hands receipt as exported by the audit export (`include=receipts`).
export type HandsReceipt = Record<string, any>;

const ENVELOPE_FIELDS = [
  "id",
  "task_id",
  "step_id",
  "site",
  "action_types",
  "verdict",
  "supersedes",
];
const SPKI_ED25519_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as object).sort()) {
      out[key] = sortKeys((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

/** The byte string that is hashed and signed. */
export function canonicalJson(value: unknown): Buffer {
  const text = JSON.stringify(sortKeys(value)).replace(
    /[\u007f-￿]/g,
    (ch) => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0"),
  );
  return Buffer.from(text, "utf8");
}

function sameJson(a: unknown, b: unknown): boolean {
  return canonicalJson(a).equals(canonicalJson(b));
}

/** Verify one receipt against a published key set. Never throws on a bad receipt. */
export function verifyReceipt(
  receipt: HandsReceipt,
  keySet: ReceiptKeySet,
): ReceiptVerification {
  try {
    if (receipt.alg !== "ed25519")
      return { valid: false, reason: "not_offline_verifiable" };
    const { bundle, signed } = receipt;
    const digest = createHash("sha256")
      .update(canonicalJson(bundle))
      .digest("hex");
    if (digest !== receipt.bundle_hash)
      return { valid: false, reason: "bundle_hash_mismatch" };
    if (!sameJson(signed.bundle, bundle))
      return { valid: false, reason: "bundle_not_signed" };
    for (const field of ENVELOPE_FIELDS) {
      if (!sameJson(signed[field] ?? null, receipt[field] ?? null)) {
        return { valid: false, reason: `envelope_mismatch:${field}` };
      }
    }
    const key = keySet.keys.find((k) => k.kid === receipt.key_version);
    if (!key || key.alg !== "Ed25519")
      return { valid: false, reason: "unknown_key" };
    const raw = Buffer.from(key.public_key, "base64url");
    const publicKey = createPublicKey({
      key: Buffer.concat([SPKI_ED25519_PREFIX, raw]),
      format: "der",
      type: "spki",
    });
    const ok = verify(
      null,
      canonicalJson(signed),
      publicKey,
      Buffer.from(receipt.signature, "hex"),
    );
    return ok
      ? { valid: true, keyStatus: key.status }
      : { valid: false, reason: "bad_signature" };
  } catch {
    return { valid: false, reason: "bad_signature" };
  }
}
