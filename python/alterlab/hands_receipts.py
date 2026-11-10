"""Offline verification of signed Hands receipts (#39829).

A receipt is trusted when (1) its Ed25519 signature over the canonical JSON of ``signed`` verifies
under the key named by ``key_version`` in the published key set (``GET /api/v1/hands/receipt-keys``),
(2) ``sha256(canonical(bundle))`` equals ``bundle_hash``, and (3) the signed envelope agrees with the
fields shown beside it. Nothing here calls the network; retired keys verify as long as the key set
still lists them.

Requires the `cryptography` package, imported lazily like :mod:`alterlab.crypto`.

Usage:
    from alterlab.hands_receipts import verify_receipt

    result = verify_receipt(receipt, key_set)
    if not result.valid:
        print(result.reason)

Canonical JSON: object keys sorted, separators ``,`` and ``:``, non-ASCII escaped as ``\\uXXXX``.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

# Receipt fields that must equal the same field inside the signed envelope.
_ENVELOPE_FIELDS = ("id", "task_id", "step_id", "site", "action_types", "verdict", "supersedes")


@dataclass
class ReceiptVerification:
    valid: bool
    reason: Optional[str] = None
    key_status: Optional[str] = None


def canonical_json(value: Any) -> bytes:
    """The byte string that is hashed and signed."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_receipt(receipt: Mapping[str, Any], key_set: Mapping[str, Any]) -> ReceiptVerification:
    """Verify one receipt against a published key set. Never raises on a bad receipt."""
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
        Ed25519PublicKey,
    )

    try:
        if receipt.get("alg") != "ed25519":
            return ReceiptVerification(False, "not_offline_verifiable")
        bundle = receipt["bundle"]
        signed: Dict[str, Any] = receipt["signed"]
        digest = hashlib.sha256(canonical_json(bundle)).hexdigest()
        if digest != receipt.get("bundle_hash"):
            return ReceiptVerification(False, "bundle_hash_mismatch")
        if signed.get("bundle") != bundle:
            return ReceiptVerification(False, "bundle_not_signed")
        for field in _ENVELOPE_FIELDS:
            if signed.get(field) != receipt.get(field):
                return ReceiptVerification(False, f"envelope_mismatch:{field}")
        key = next(
            (k for k in key_set.get("keys", []) if k.get("kid") == receipt.get("key_version")),
            None,
        )
        if key is None or key.get("alg") != "Ed25519":
            return ReceiptVerification(False, "unknown_key")
        public = Ed25519PublicKey.from_public_bytes(_b64u_decode(key["public_key"]))
        public.verify(bytes.fromhex(receipt["signature"]), canonical_json(signed))
        return ReceiptVerification(True, None, key.get("status"))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return ReceiptVerification(False, "bad_signature")
