"""Regression tests for fail-closed invariant-attack verdict semantics."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest


ATTACK_DIR = Path(__file__).resolve().parents[1] / "scripts" / "invariant_attacks"
sys.path.insert(0, str(ATTACK_DIR))

import attack4_forgery as attack4  # noqa: E402
import attack5_crash_sqlite as attack5  # noqa: E402
import attack6_key_misuse as attack6  # noqa: E402
import attack_combined as combined  # noqa: E402
import redact_evidence as redactor  # noqa: E402


def test_combined_requires_every_storm_variant_to_start() -> None:
    started = Counter({tag: 1 for tag in combined.REQUIRED_STORM_VECTOR_TAGS})

    assert combined.all_required_storm_vectors_started(started)


@pytest.mark.parametrize("missing", combined.REQUIRED_STORM_VECTOR_TAGS)
def test_combined_fails_closed_when_storm_variant_did_not_start(missing: str) -> None:
    started = Counter({tag: 1 for tag in combined.REQUIRED_STORM_VECTOR_TAGS})
    del started[missing]

    assert not combined.all_required_storm_vectors_started(started)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 0,
            },
            "HELD",
        ),
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 1,
            },
            "PARTIAL",
        ),
        (
            {
                "crash_happened": True,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 1,
                "proof_pending_count": 0,
            },
            "BROKE",
        ),
        (
            {
                "crash_happened": False,
                "no_double_by_total": True,
                "no_double_by_key": True,
                "no_receipt_without_charge": True,
                "silent_orphan_count": 0,
                "proof_pending_count": 0,
            },
            "BROKE",
        ),
    ],
)
def test_attack5_verdict_distinguishes_pending_from_corruption(
    kwargs: dict, expected: str
) -> None:
    assert attack5.classify_verdict(**kwargs) == expected


def test_attack5_refunds_must_correlate_to_the_exact_debit(monkeypatch) -> None:
    def fake_db_rows(query: str, params=()):
        if "action='debit'" in query:
            return [
                {"entry_id": "ledger-1", "amount": -2, "operation_key": "idem-1"},
                {"entry_id": "ledger-2", "amount": -2, "operation_key": "idem-2"},
            ]
        if "action='refund'" in query:
            return [
                {
                    "entry_id": "refund-ledger-1",
                    "amount": 2,
                    "correlation_id": "ledger-1",
                }
            ]
        return []

    monkeypatch.setattr(attack5.A, "db_rows", fake_db_rows)

    analysis = attack5.ledger_analysis("agt-test", {"idem-1", "idem-2"})

    assert analysis["correlated_refunded_debits"] == 1
    assert analysis["silent_orphan_debits"] == 1


def test_attack6_requires_exact_status_and_reason() -> None:
    expected = {"status": 403, "json": {"detail": {"error": "invalid_api_key"}}}

    assert attack6.matches_response(expected, status=403, reason="invalid_api_key")
    assert not attack6.matches_response(
        {**expected, "status": None}, status=403, reason="invalid_api_key"
    )
    assert not attack6.matches_response(
        {**expected, "status": 500}, status=403, reason="invalid_api_key"
    )
    assert not attack6.matches_response(
        expected, status=403, reason="missing_credentials"
    )
    assert attack6.matches_response({"status": 204}, status=204)


def test_forgery_cases_include_ledger_binding_and_fail_closed_if_missing() -> None:
    bundle = {
        "receipt": {
            "wallet_id": "agt-victim",
        },
        "signing_input": '{"ledger_entry_id":"ledger-original"}',
    }

    tampers = attack4.A.signed_receipt_tamper_cases(bundle)

    assert tampers["ledger_entry_id"] == (
        "ledger-original",
        "ledger-forged-entry",
    )
    missing = attack4.A.signed_receipt_tamper_cases({"receipt": {}})
    assert missing["ledger_entry_id"][0] == "<missing-ledger-entry-id>"


def test_evidence_redaction_removes_credentials_and_wallets() -> None:
    credential = "b2a_" + "A" * 32
    evidence = {
        "victim_wallet": "agt-secret-tenant",
        "nested": {
            "api_key": credential,
            "message": f"leaked {credential} for agt-deadbeef1234",
        },
        "receipt_id": "rcpt-public-proof-reference",
    }

    redacted = redactor.redact_evidence(evidence)

    assert redacted["victim_wallet"] == "<redacted>"
    assert redacted["nested"]["api_key"] == "<redacted>"
    assert redacted["nested"]["message"] == (
        "leaked <redacted-credential> for <redacted-wallet>"
    )
    assert redacted["receipt_id"] == "rcpt-public-proof-reference"
    assert not redactor.contains_full_credential(redacted)
    assert not redactor.contains_wallet_identifier(redacted)
