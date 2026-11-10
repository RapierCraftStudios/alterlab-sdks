/**
 * Client-side cookie encryption for zero-knowledge session storage.
 *
 * Encrypts cookies locally before sending to the AlterLab API using
 * Node.js built-in crypto module. The server never sees plaintext
 * cookie values.
 *
 * Usage:
 *   import { encryptCookies } from 'alterlab/crypto';
 *
 *   const result = encryptCookies(
 *     { session_id: 'abc123', token: 'xyz789' },
 *     serverPublicKeyPem
 *   );
 */

import { createCipheriv, publicEncrypt, randomBytes, constants } from "crypto";

/** Result of client-side cookie encryption. */
export interface EncryptedCookiePayload {
  /** Base64(IV) + "." + Base64(ciphertext+authTag) */
  encrypted_cookies: string;
  /** Base64 RSA-OAEP wrapped AES-256 session key */
  wrapped_key: string;
  /** Plaintext cookie names (no values) for UI display */
  cookie_names: string[];
}

/**
 * Encrypt cookies client-side for zero-knowledge storage.
 *
 * Generates an ephemeral AES-256-GCM key, encrypts the cookie dict,
 * then wraps the AES key with the server's RSA-OAEP-SHA256 public key.
 *
 * @param cookies - Cookie name-value mapping to encrypt
 * @param serverPublicKeyPem - PEM-encoded RSA public key from the server
 * @returns EncryptedCookiePayload ready to send to the sessions API
 */
export function encryptCookies(
  cookies: Record<string, string>,
  serverPublicKeyPem: string
): EncryptedCookiePayload {
  if (!cookies || Object.keys(cookies).length === 0) {
    throw new Error("cookies must be a non-empty object");
  }

  // Generate ephemeral AES-256 key (32 bytes) and IV (12 bytes for GCM)
  const sessionKey = randomBytes(32);
  const iv = randomBytes(12);

  // Encrypt cookie JSON with AES-256-GCM
  const plaintext = Buffer.from(JSON.stringify(cookies), "utf-8");
  const cipher = createCipheriv("aes-256-gcm", sessionKey, iv);
  const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const authTag = cipher.getAuthTag();

  // Combine ciphertext + auth tag (matches Web Crypto API behavior)
  const ciphertextWithTag = Buffer.concat([encrypted, authTag]);

  // Wrap AES session key with RSA-OAEP-SHA256
  const wrappedKey = publicEncrypt(
    {
      key: serverPublicKeyPem,
      padding: constants.RSA_PKCS1_OAEP_PADDING,
      oaepHash: "sha256",
    },
    sessionKey
  );

  // Format: base64(iv).base64(ciphertext+authTag)
  const encryptedCookies =
    iv.toString("base64") + "." + ciphertextWithTag.toString("base64");

  // Zero out the session key from memory
  sessionKey.fill(0);

  return {
    encrypted_cookies: encryptedCookies,
    wrapped_key: wrappedKey.toString("base64"),
    cookie_names: Object.keys(cookies),
  };
}
