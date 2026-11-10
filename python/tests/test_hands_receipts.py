"""Offline Hands receipt verifier (#39829), driven by the shared conformance fixtures."""

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from alterlab.hands_receipts import canonical_json, verify_receipt  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "hands_conformance" / "fixtures"
DATA = json.loads((FIXTURES / "receipts.json").read_text())


def test_fixture_receipts_verify_including_retired_key():
    assert len(DATA["receipts"]) >= 6
    for receipt in DATA["receipts"]:
        result = verify_receipt(receipt, DATA["key_set"])
        assert result.valid and result.reason is None
        assert result.key_status in ("active", "retired")
    assert any(k["status"] == "retired" for k in DATA["key_set"]["keys"])


def test_retired_key_is_reported_retired():
    result = verify_receipt(DATA["receipts"][0], DATA["key_set"])
    assert result.key_status == "retired"


def test_tampered_receipts_fail():
    for case in DATA["tampered"]:
        assert not verify_receipt(case, DATA["key_set"]).valid


def test_each_tamper_reports_a_reason():
    receipt = copy.deepcopy(DATA["receipts"][0])
    receipt["bundle"]["status"] = 418
    assert verify_receipt(receipt, DATA["key_set"]).reason == "bundle_hash_mismatch"
    receipt = copy.deepcopy(DATA["receipts"][0])
    receipt["site"] = "other.test"
    assert verify_receipt(receipt, DATA["key_set"]).reason == "envelope_mismatch:site"
    receipt = copy.deepcopy(DATA["receipts"][0])
    receipt["key_version"] = "nope"
    assert verify_receipt(receipt, DATA["key_set"]).reason == "unknown_key"


def test_legacy_hmac_is_not_offline_verifiable():
    receipt = {**DATA["receipts"][0], "alg": "hmac-sha256"}
    assert verify_receipt(receipt, DATA["key_set"]).reason == "not_offline_verifiable"


def test_malformed_receipt_never_raises():
    assert not verify_receipt({"alg": "ed25519"}, DATA["key_set"]).valid
    assert not verify_receipt({}, {}).valid


def test_canonical_json_escapes_non_ascii_and_sorts():
    assert canonical_json({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'
    for sample in DATA["canonical"]:
        assert canonical_json(sample["value"]).decode() == sample["canonical"]
