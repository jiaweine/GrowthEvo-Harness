from __future__ import annotations

from base64 import b64encode
import json

import pytest

from growthevo.evolution.promotion_manifest import (
    AuthorityVerdict,
    PromotionSubject,
    PromotionTransition,
)
from growthevo.evolution.signed_attestation import (
    AuthorityAttestationClaims,
    AuthoritySignerRule,
    DSSEEnvelope,
    DSSESignature,
    SignatureVerificationResult,
    SignedAttestationPolicy,
    verify_authority_attestation,
)


class _Verifier:
    verifier_id = "strict-schema-verifier"

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        return SignatureVerificationResult(
            verifier_id=self.verifier_id,
            signer_identity="trusted-signer",
            issuer="trusted-issuer",
            verification_material_fingerprint="material-fp",
            transparency_log_verified=True,
            timestamp_verified=True,
        )


def _subject() -> PromotionSubject:
    return PromotionSubject(
        experiment_id="exp-schema",
        candidate_name="candidate",
        candidate_contract_fingerprint="candidate-fp",
        promotion_artifact_fingerprint="artifact-fp",
        plan_fingerprint="plan-fp",
        commit_sha="commit-sha",
    )


def _policy() -> SignedAttestationPolicy:
    return SignedAttestationPolicy(
        policy_id="strict-schema-policy",
        signer_rules=(
            AuthoritySignerRule(
                authority_id="integrity",
                allowed_signer_identities=("trusted-signer",),
                allowed_issuers=("trusted-issuer",),
                allowed_verifier_ids=("strict-schema-verifier",),
            ),
        ),
    )


def _document() -> dict[str, object]:
    claims = AuthorityAttestationClaims(
        authority_id="integrity",
        evidence_type="integrity.v1",
        protocol_fingerprint="integrity-protocol-v1",
        artifact_fingerprint="integrity-artifact-v1",
        verdict=AuthorityVerdict.SATISFIED,
        authorized_transitions=(PromotionTransition.FINAL_PROMOTION,),
        evidence_epoch=1,
    )
    return claims.statement_payload(_subject())


def _envelope(document: dict[str, object]) -> DSSEEnvelope:
    return DSSEEnvelope.from_payload(
        payload_type="application/vnd.in-toto+json",
        payload=json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        signatures=(
            DSSESignature(keyid="", sig=b64encode(b"signature").decode("ascii")),
        ),
    )


@pytest.mark.parametrize(
    "field",
    (
        "authority_id",
        "evidence_type",
        "protocol_fingerprint",
        "artifact_fingerprint",
        "source_chain_head",
        "details_fingerprint",
    ),
)
def test_signed_predicate_string_fields_are_not_coerced(field: str) -> None:
    document = _document()
    predicate = dict(document["predicate"])  # type: ignore[arg-type]
    predicate[field] = 123
    document["predicate"] = predicate
    with pytest.raises(ValueError, match="must be a non-empty string"):
        verify_authority_attestation(
            envelope=_envelope(document),
            expected_subject=_subject(),
            policy=_policy(),
            verifier=_Verifier(),
        )
