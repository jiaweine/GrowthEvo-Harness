from __future__ import annotations

from base64 import b64encode
from dataclasses import replace
import json

import pytest

from growthevo.evolution.promotion_manifest import (
    AuthorityRequirement,
    AuthorityVerdict,
    PromotionEvidenceLedger,
    PromotionEvidencePolicy,
    PromotionSubject,
    PromotionTransition,
    TransitionPolicy,
)
from growthevo.evolution.signed_attestation import (
    AuthorityAttestationClaims,
    AuthoritySignerRule,
    DSSEEnvelope,
    DSSESignature,
    GROWTHEVO_AUTHORITY_PREDICATE_V1,
    IN_TOTO_DSSE_PAYLOAD_TYPE,
    IN_TOTO_STATEMENT_V1,
    SignatureVerificationResult,
    SignedAttestationPolicy,
    dsse_pae,
    verify_authority_attestation,
)


SIGNER = "https://github.com/jiaweine/GrowthEvo-Harness/.github/workflows/evidence.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
VERIFIER = "sigstore-python-offline-v1"


def _subject(**overrides: str) -> PromotionSubject:
    values = {
        "experiment_id": "exp-signed-42",
        "candidate_name": "challenger-v3",
        "candidate_contract_fingerprint": "candidate-contract-fp",
        "promotion_artifact_fingerprint": "promotion-artifact-fp",
        "plan_fingerprint": "canary-plan-fp",
        "commit_sha": "0123456789abcdef",
    }
    values.update(overrides)
    return PromotionSubject(**values)


def _claims(**overrides: object) -> AuthorityAttestationClaims:
    values: dict[str, object] = {
        "authority_id": "online_safety",
        "evidence_type": "online_safety.v1",
        "protocol_fingerprint": "online-safety-protocol-v1",
        "artifact_fingerprint": "online-safety-artifact-v1",
        "verdict": AuthorityVerdict.SATISFIED,
        "authorized_transitions": (
            PromotionTransition.ADVANCE_STAGE,
            PromotionTransition.FINAL_PROMOTION,
        ),
        "evidence_epoch": 7,
        "source_chain_head": "upstream-audit-chain-head",
        "details_fingerprint": "upstream-details-fingerprint",
    }
    values.update(overrides)
    return AuthorityAttestationClaims(**values)  # type: ignore[arg-type]


def _rule(**overrides: object) -> AuthoritySignerRule:
    values: dict[str, object] = {
        "authority_id": "online_safety",
        "allowed_signer_identities": (SIGNER,),
        "allowed_issuers": (ISSUER,),
        "allowed_verifier_ids": (VERIFIER,),
        "require_transparency_log": True,
        "require_timestamp": True,
    }
    values.update(overrides)
    return AuthoritySignerRule(**values)  # type: ignore[arg-type]


def _policy(**overrides: object) -> SignedAttestationPolicy:
    values: dict[str, object] = {
        "policy_id": "signed-authority-trust-v1",
        "signer_rules": (_rule(),),
    }
    values.update(overrides)
    return SignedAttestationPolicy(**values)  # type: ignore[arg-type]


def _envelope(
    subject: PromotionSubject,
    *,
    claims: AuthorityAttestationClaims | None = None,
    document: dict[str, object] | None = None,
    payload_type: str = IN_TOTO_DSSE_PAYLOAD_TYPE,
) -> DSSEEnvelope:
    if document is None:
        document = (claims or _claims()).statement_payload(subject)
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return DSSEEnvelope.from_payload(
        payload_type=payload_type,
        payload=payload,
        signatures=(DSSESignature(keyid="", sig=b64encode(b"signature").decode("ascii")),),
    )


class FakeVerifier:
    def __init__(
        self,
        *,
        verifier_id: str = VERIFIER,
        signer_identity: str = SIGNER,
        issuer: str = ISSUER,
        transparency_log_verified: bool = True,
        timestamp_verified: bool = True,
        receipt_verifier_id: str | None = None,
        expected_envelope_fingerprint: str | None = None,
    ) -> None:
        self.verifier_id = verifier_id
        self.signer_identity = signer_identity
        self.issuer = issuer
        self.transparency_log_verified = transparency_log_verified
        self.timestamp_verified = timestamp_verified
        self.receipt_verifier_id = receipt_verifier_id or verifier_id
        self.expected_envelope_fingerprint = expected_envelope_fingerprint
        self.calls = 0

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        self.calls += 1
        if (
            self.expected_envelope_fingerprint is not None
            and envelope.fingerprint != self.expected_envelope_fingerprint
        ):
            raise ValueError("cryptographic signature verification failed")
        # Exercise the exact DSSE PAE bytes that a real verifier signs/verifies.
        assert envelope.pae == dsse_pae(envelope.payload_type, envelope.payload_bytes)
        return SignatureVerificationResult(
            verifier_id=self.receipt_verifier_id,
            signer_identity=self.signer_identity,
            issuer=self.issuer,
            verification_material_fingerprint="verification-material-fp",
            verified_signature_count=1,
            transparency_log_verified=self.transparency_log_verified,
            timestamp_verified=self.timestamp_verified,
            transparency_log_entry_fingerprint="rekor-entry-fp",
            timestamp_fingerprint="trusted-time-fp",
        )


def test_dsse_pae_matches_spec_shape() -> None:
    assert dsse_pae("foo", b"bar") == b"DSSEv1 3 foo 3 bar"
    assert dsse_pae("application/vnd.in-toto+json", b"{}") == (
        b"DSSEv1 28 application/vnd.in-toto+json 2 {}"
    )


def test_envelope_rejects_invalid_base64_and_empty_signatures() -> None:
    with pytest.raises(ValueError, match="valid base64"):
        DSSEEnvelope(
            payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
            payload="not-base64!",
            signatures=(DSSESignature(keyid="", sig=b64encode(b"sig").decode("ascii")),),
        )
    with pytest.raises(ValueError, match="at least one signature"):
        DSSEEnvelope(
            payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
            payload=b64encode(b"{}").decode("ascii"),
            signatures=(),
        )


def test_verified_statement_maps_signer_identity_into_authority_evidence() -> None:
    subject = _subject()
    envelope = _envelope(subject)
    verifier = FakeVerifier(expected_envelope_fingerprint=envelope.fingerprint)
    verified = verify_authority_attestation(
        envelope=envelope,
        expected_subject=subject,
        policy=_policy(),
        verifier=verifier,
    )
    assert verifier.calls == 1
    assert verified.evidence.authority_id == "online_safety"
    assert verified.evidence.producer == SIGNER
    assert verified.evidence.subject_fingerprint == subject.fingerprint
    assert verified.evidence.evidence_epoch == 7
    assert verified.evidence.authorized_transitions == (
        PromotionTransition.ADVANCE_STAGE,
        PromotionTransition.FINAL_PROMOTION,
    )
    assert verified.evidence.details_fingerprint != "upstream-details-fingerprint"
    assert verified.envelope_fingerprint == envelope.fingerprint


def test_signed_evidence_integrates_with_phase14_allowlisted_ledger() -> None:
    subject = _subject()
    verified = verify_authority_attestation(
        envelope=_envelope(subject),
        expected_subject=subject,
        policy=_policy(),
        verifier=FakeVerifier(),
    )
    ledger = PromotionEvidenceLedger(subject)
    ledger.append(verified.evidence)
    authority_policy = PromotionEvidencePolicy(
        policy_id="signed-online-safety-only-v1",
        transitions=(
            TransitionPolicy(
                transition=PromotionTransition.FINAL_PROMOTION,
                requirements=(
                    AuthorityRequirement(
                        authority_id="online_safety",
                        allowed_evidence_types=("online_safety.v1",),
                        allowed_protocol_fingerprints=("online-safety-protocol-v1",),
                        allowed_producers=(SIGNER,),
                        minimum_evidence_epoch=7,
                    ),
                ),
            ),
        ),
    )
    manifest = ledger.build_manifest(
        policy=authority_policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    assert ledger.evaluate(manifest=manifest, policy=authority_policy).authorized


@pytest.mark.parametrize(
    ("verifier", "message"),
    (
        (FakeVerifier(signer_identity="untrusted-signer"), "signer identity"),
        (FakeVerifier(issuer="https://evil.example"), "issuer"),
        (FakeVerifier(verifier_id="unapproved-verifier"), "verifier is not approved"),
        (
            FakeVerifier(receipt_verifier_id="different-receipt-verifier"),
            "receipt verifier id",
        ),
        (
            FakeVerifier(transparency_log_verified=False),
            "transparency-log verification",
        ),
        (FakeVerifier(timestamp_verified=False), "timestamp verification"),
    ),
)
def test_identity_verifier_and_transparency_policy_fail_closed(
    verifier: FakeVerifier,
    message: str,
) -> None:
    subject = _subject()
    with pytest.raises(ValueError, match=message):
        verify_authority_attestation(
            envelope=_envelope(subject),
            expected_subject=subject,
            policy=_policy(),
            verifier=verifier,
        )


def test_policy_can_explicitly_allow_private_pki_without_tlog_or_timestamp() -> None:
    subject = _subject()
    private_rule = _rule(
        require_transparency_log=False,
        require_timestamp=False,
        allowed_issuers=("private-ca",),
        allowed_signer_identities=("kms://growth/safety",),
        allowed_verifier_ids=("enterprise-pki-verifier-v1",),
    )
    verified = verify_authority_attestation(
        envelope=_envelope(subject),
        expected_subject=subject,
        policy=_policy(signer_rules=(private_rule,)),
        verifier=FakeVerifier(
            verifier_id="enterprise-pki-verifier-v1",
            signer_identity="kms://growth/safety",
            issuer="private-ca",
            transparency_log_verified=False,
            timestamp_verified=False,
        ),
    )
    assert verified.evidence.producer == "kms://growth/safety"


def test_cross_subject_statement_is_rejected_even_if_signature_verifier_succeeds() -> None:
    signed_for = _subject(candidate_name="other-candidate")
    expected = _subject()
    with pytest.raises(ValueError, match="subject digest"):
        verify_authority_attestation(
            envelope=_envelope(signed_for),
            expected_subject=expected,
            policy=_policy(),
            verifier=FakeVerifier(),
        )


def test_predicate_subject_duplicate_binding_is_checked() -> None:
    subject = _subject()
    document = _claims().statement_payload(subject)
    predicate = dict(document["predicate"])  # type: ignore[arg-type]
    predicate["subject_fingerprint"] = _subject(candidate_name="other").fingerprint
    document["predicate"] = predicate
    with pytest.raises(ValueError, match="predicate subject fingerprint"):
        verify_authority_attestation(
            envelope=_envelope(subject, document=document),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )


def test_wrong_statement_predicate_and_payload_types_are_rejected() -> None:
    subject = _subject()
    statement = _claims().statement_payload(subject)
    statement["_type"] = "https://example.invalid/Statement/v9"
    with pytest.raises(ValueError, match="statement type"):
        verify_authority_attestation(
            envelope=_envelope(subject, document=statement),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )

    statement = _claims().statement_payload(subject)
    statement["predicateType"] = "https://example.invalid/predicate"
    with pytest.raises(ValueError, match="predicate type"):
        verify_authority_attestation(
            envelope=_envelope(subject, document=statement),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )

    with pytest.raises(ValueError, match="payload type"):
        verify_authority_attestation(
            envelope=_envelope(subject, payload_type="application/json"),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )


def test_extra_statement_or_predicate_fields_are_rejected() -> None:
    subject = _subject()
    document = _claims().statement_payload(subject)
    document["unsigned_hint"] = "ignore me"
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        verify_authority_attestation(
            envelope=_envelope(subject, document=document),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )

    document = _claims().statement_payload(subject)
    predicate = dict(document["predicate"])  # type: ignore[arg-type]
    predicate["replacement_candidate"] = "evil"
    document["predicate"] = predicate
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        verify_authority_attestation(
            envelope=_envelope(subject, document=document),
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )


def test_tampered_payload_is_rejected_by_cryptographic_verifier_boundary() -> None:
    subject = _subject()
    original = _envelope(subject)
    verifier = FakeVerifier(expected_envelope_fingerprint=original.fingerprint)
    tampered_document = _claims(artifact_fingerprint="tampered-artifact").statement_payload(subject)
    tampered = _envelope(subject, document=tampered_document)
    with pytest.raises(ValueError, match="signature verification failed"):
        verify_authority_attestation(
            envelope=tampered,
            expected_subject=subject,
            policy=_policy(),
            verifier=verifier,
        )


def test_semantically_equal_json_has_same_statement_identity_but_different_envelope_identity() -> None:
    subject = _subject()
    document = _claims().statement_payload(subject)
    compact = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    pretty = json.dumps(document, sort_keys=False, indent=2).encode("utf-8")
    signature = DSSESignature(keyid="", sig=b64encode(b"signature").decode("ascii"))
    envelope_a = DSSEEnvelope.from_payload(
        payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
        payload=compact,
        signatures=(signature,),
    )
    envelope_b = DSSEEnvelope.from_payload(
        payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
        payload=pretty,
        signatures=(signature,),
    )
    verified_a = verify_authority_attestation(
        envelope=envelope_a,
        expected_subject=subject,
        policy=_policy(),
        verifier=FakeVerifier(),
    )
    verified_b = verify_authority_attestation(
        envelope=envelope_b,
        expected_subject=subject,
        policy=_policy(),
        verifier=FakeVerifier(),
    )
    assert verified_a.statement_fingerprint == verified_b.statement_fingerprint
    assert verified_a.envelope_fingerprint != verified_b.envelope_fingerprint
    assert verified_a.fingerprint != verified_b.fingerprint


def test_signature_verification_result_and_policy_fingerprints_bind_security_inputs() -> None:
    baseline = SignatureVerificationResult(
        verifier_id=VERIFIER,
        signer_identity=SIGNER,
        issuer=ISSUER,
        verification_material_fingerprint="material",
        transparency_log_verified=True,
        timestamp_verified=True,
    )
    changed = replace(baseline, signer_identity="other")
    assert baseline.fingerprint != changed.fingerprint

    policy = _policy()
    assert policy.fingerprint != _policy(
        signer_rules=(_rule(require_timestamp=False),)
    ).fingerprint
    assert policy.fingerprint != _policy(
        predicate_type=GROWTHEVO_AUTHORITY_PREDICATE_V1 + "/v2"
    ).fingerprint


def test_unknown_authority_has_no_ambient_trust() -> None:
    subject = _subject()
    envelope = _envelope(subject, claims=_claims(authority_id="unknown_authority"))
    with pytest.raises(ValueError, match="no signed-attestation trust rule"):
        verify_authority_attestation(
            envelope=envelope,
            expected_subject=subject,
            policy=_policy(),
            verifier=FakeVerifier(),
        )


def test_statement_constants_match_expected_standard_namespaces() -> None:
    assert IN_TOTO_STATEMENT_V1 == "https://in-toto.io/Statement/v1"
    assert IN_TOTO_DSSE_PAYLOAD_TYPE == "application/vnd.in-toto+json"
    assert GROWTHEVO_AUTHORITY_PREDICATE_V1.endswith("/attestation/promotion-authority/v1")
