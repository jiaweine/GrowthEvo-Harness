from __future__ import annotations

import json

import pytest

from growthevo.evolution.promotion_manifest import PromotionSubject, PromotionTransition
from growthevo.evolution.signed_attestation import (
    DSSEEnvelope,
    DSSESignature,
    IN_TOTO_DSSE_PAYLOAD_TYPE,
    SignatureVerificationResult,
)
from growthevo.evolution.slsa_build_provenance import VerifiedSLSABuildProvenance
from growthevo.evolution.slsa_vsa import (
    GROWTHEVO_VSA_EXTENSION_V1,
    SLSA_VSA_V1,
    SLSAVSAConsumerPolicy,
    SLSAVSAProductionSpec,
    VSAArtifactIdentity,
    VSAResourceDescriptor,
    VSAVerifierTrust,
    produce_slsa_vsa,
    sign_slsa_vsa,
    verify_slsa_vsa,
)


DIGEST = "a" * 64
COMMIT = "b" * 40
PROVENANCE_DIGEST = "c" * 64
POLICY_DIGEST = "d" * 64
VERIFIER_ID = "https://verifier.example/growthevo"
SIGNER = "https://github.com/example/verifier/.github/workflows/vsa.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
CRYPTO_VERIFIER_ID = "sigstore-vsa-v1"
RESOURCE = "https://packages.example/example_pkg-1.0.0-py3-none-any.whl"
POLICY_URI = "https://policy.example/slsa-build-v1"
PROVENANCE_URI = "https://pypi.org/integrity/example/1.0.0/example_pkg-1.0.0-py3-none-any.whl/provenance"


def _verified(*, level: int = 2, commit: str = COMMIT) -> VerifiedSLSABuildProvenance:
    return VerifiedSLSABuildProvenance(
        distribution_filename="example_pkg-1.0.0-py3-none-any.whl",
        distribution_sha256=DIGEST,
        publisher_identity="pypi-trusted-publisher:github:example/repo:.github/workflows/release.yml",
        issuer=ISSUER,
        builder_id="https://github.com/example/repo/.github/workflows/release.yml@refs/tags/v1.0.0",
        trusted_build_level=level,
        build_type="https://actions.github.io/buildtypes/workflow/v1",
        external_parameters_fingerprint="external-fingerprint",
        resolved_dependencies_fingerprint="dependencies-fingerprint",
        source_dependency_uri="git+https://github.com/example/repo@refs/tags/v1.0.0",
        source_commit_sha=commit,
        predicate_fingerprint="predicate-fingerprint",
        verification_material_fingerprint="verification-material-fingerprint",
        transparency_log_fingerprint="transparency-log-fingerprint",
        provenance_fingerprint=PROVENANCE_DIGEST,
        expectation_fingerprint="build-expectation-fingerprint",
    )


def _production_spec(*, level: int = 2) -> SLSAVSAProductionSpec:
    return SLSAVSAProductionSpec(
        verifier_id=VERIFIER_ID,
        resource_uri=RESOURCE,
        policy=VSAResourceDescriptor(uri=POLICY_URI, sha256=POLICY_DIGEST),
        provenance_uri=PROVENANCE_URI,
        build_level=level,
        verifier_versions=(("growthevo", "phase19"),),
        slsa_version="1.2",
        time_verified="2026-09-08T00:00:00Z",
    )


def _subject(commit: str = COMMIT) -> PromotionSubject:
    return PromotionSubject(
        experiment_id="exp",
        candidate_name="candidate",
        candidate_contract_fingerprint="candidate-contract",
        promotion_artifact_fingerprint="promotion-artifact",
        plan_fingerprint="plan",
        commit_sha=commit,
    )


class FakeSigner:
    signer_id = "fake-vsa-signer"

    def sign(self, *, payload_type: str, payload: bytes) -> DSSEEnvelope:
        return DSSEEnvelope.from_payload(
            payload_type=payload_type,
            payload=payload,
            signatures=(DSSESignature(keyid="fake", sig="c2ln"),),
        )


class WrongPayloadSigner(FakeSigner):
    def sign(self, *, payload_type: str, payload: bytes) -> DSSEEnvelope:
        return super().sign(payload_type=payload_type, payload=payload + b" ")


class FakeVerifier:
    verifier_id = CRYPTO_VERIFIER_ID

    def __init__(
        self,
        *,
        signer: str = SIGNER,
        issuer: str = ISSUER,
        receipt_verifier_id: str = CRYPTO_VERIFIER_ID,
        transparency: bool = True,
        timestamp: bool = True,
    ) -> None:
        self._result = SignatureVerificationResult(
            verifier_id=receipt_verifier_id,
            signer_identity=signer,
            issuer=issuer,
            verification_material_fingerprint="material",
            verified_signature_count=1,
            transparency_log_verified=transparency,
            timestamp_verified=timestamp,
            transparency_log_entry_fingerprint="tlog",
            timestamp_fingerprint="time",
        )

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        assert envelope.payload_type == IN_TOTO_DSSE_PAYLOAD_TYPE
        return self._result


def _consumer_policy(*, max_level: int = 2, minimum_level: int = 2) -> SLSAVSAConsumerPolicy:
    return SLSAVSAConsumerPolicy(
        policy_id="delegated-slsa-build-v1",
        trusted_verifiers=(
            VSAVerifierTrust(
                verifier_id=VERIFIER_ID,
                allowed_signer_identities=(SIGNER,),
                allowed_issuers=(ISSUER,),
                allowed_attestation_verifier_ids=(CRYPTO_VERIFIER_ID,),
                maximum_build_level=max_level,
            ),
        ),
        expected_policy_uri=POLICY_URI,
        allowed_policy_sha256s=(POLICY_DIGEST,),
        minimum_build_level=minimum_level,
    )


def _artifact(verified: VerifiedSLSABuildProvenance | None = None) -> VSAArtifactIdentity:
    value = verified or _verified()
    return VSAArtifactIdentity(
        name=value.distribution_filename,
        sha256=value.distribution_sha256,
        resource_uri=RESOURCE,
        expected_source_commit_sha=value.source_commit_sha,
        expected_source_verification_fingerprint=value.fingerprint,
        expected_input_attestation_sha256=value.provenance_fingerprint,
    )


def _envelope(verified: VerifiedSLSABuildProvenance | None = None, *, level: int = 2) -> DSSEEnvelope:
    value = verified or _verified()
    produced = produce_slsa_vsa(verified_provenance=value, spec=_production_spec(level=level))
    return sign_slsa_vsa(produced=produced, signer=FakeSigner())


def _mutate(envelope: DSSEEnvelope, mutate) -> DSSEEnvelope:
    document = json.loads(envelope.payload_bytes.decode("utf-8"))
    mutate(document)
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return DSSEEnvelope.from_payload(
        payload_type=envelope.payload_type,
        payload=payload,
        signatures=envelope.signatures,
    )


def test_producer_is_deterministic_and_makes_no_dependency_claim() -> None:
    verified = _verified()
    first = produce_slsa_vsa(verified_provenance=verified, spec=_production_spec())
    second = produce_slsa_vsa(verified_provenance=verified, spec=_production_spec())
    assert first.statement_bytes == second.statement_bytes
    assert first.statement_fingerprint == second.statement_fingerprint

    statement = json.loads(first.statement_bytes.decode("utf-8"))
    assert statement["predicateType"] == SLSA_VSA_V1
    predicate = statement["predicate"]
    assert predicate["verificationResult"] == "PASSED"
    assert predicate["verifiedLevels"] == ["SLSA_BUILD_LEVEL_2"]
    assert predicate["dependencyLevels"] is None
    assert predicate["inputAttestations"][0]["digest"]["sha256"] == PROVENANCE_DIGEST
    assert predicate[GROWTHEVO_VSA_EXTENSION_V1]["sourceCommitSha"] == COMMIT


def test_producer_cannot_claim_above_verified_local_trust() -> None:
    with pytest.raises(ValueError, match="above the verified local trust level"):
        produce_slsa_vsa(verified_provenance=_verified(level=2), spec=_production_spec(level=3))


def test_signer_must_return_envelope_for_exact_statement_bytes() -> None:
    produced = produce_slsa_vsa(verified_provenance=_verified(), spec=_production_spec())
    with pytest.raises(ValueError, match="different payload bytes"):
        sign_slsa_vsa(produced=produced, signer=WrongPayloadSigner())


def test_consumer_verifies_delegated_vsa_and_emits_phase14_evidence() -> None:
    verified_source = _verified()
    verified_vsa = verify_slsa_vsa(
        envelope=_envelope(verified_source),
        expected_artifact=_artifact(verified_source),
        policy=_consumer_policy(),
        verifier=FakeVerifier(),
    )
    assert verified_vsa.verified_build_level == 2
    assert verified_vsa.verifier_id == VERIFIER_ID
    assert verified_vsa.signer_identity == SIGNER
    assert verified_vsa.source_commit_sha == COMMIT

    evidence = verified_vsa.to_delegated_authority_evidence(
        subject=_subject(),
        authority_id="delegated_supply_chain",
        authorized_transitions=(PromotionTransition.FINAL_PROMOTION,),
        evidence_epoch=7,
        minimum_build_level=2,
    )
    assert evidence.evidence_type == "slsa_vsa_delegated_verification.v1"
    assert evidence.producer == VERIFIER_ID


def test_signer_and_verifier_id_must_be_an_exact_trusted_pair() -> None:
    with pytest.raises(ValueError, match="signer identity"):
        verify_slsa_vsa(
            envelope=_envelope(),
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(signer="https://evil.example/signer"),
        )

    with pytest.raises(ValueError, match="receipt verifier id"):
        verify_slsa_vsa(
            envelope=_envelope(),
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(receipt_verifier_id="different-verifier"),
        )


def test_vsa_cannot_delegate_a_level_above_consumer_trust() -> None:
    envelope = _envelope(_verified(level=3), level=3)
    with pytest.raises(ValueError, match="above this verifier's delegated trust"):
        verify_slsa_vsa(
            envelope=envelope,
            expected_artifact=_artifact(_verified(level=3)),
            policy=_consumer_policy(max_level=2),
            verifier=FakeVerifier(),
        )


def test_failed_result_resource_policy_and_dependency_claims_fail_closed() -> None:
    envelope = _envelope()

    failed = _mutate(envelope, lambda doc: doc["predicate"].__setitem__("verificationResult", "FAILED"))
    with pytest.raises(ValueError, match="not PASSED"):
        verify_slsa_vsa(
            envelope=failed,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )

    wrong_resource = _mutate(envelope, lambda doc: doc["predicate"].__setitem__("resourceUri", "https://evil/artifact"))
    with pytest.raises(ValueError, match="resourceUri"):
        verify_slsa_vsa(
            envelope=wrong_resource,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )

    wrong_policy = _mutate(
        envelope,
        lambda doc: doc["predicate"]["policy"]["digest"].__setitem__("sha256", "e" * 64),
    )
    with pytest.raises(ValueError, match="policy digest"):
        verify_slsa_vsa(
            envelope=wrong_policy,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )

    dependencies_claimed = _mutate(
        envelope,
        lambda doc: doc["predicate"].__setitem__("dependencyLevels", {"SLSA_BUILD_LEVEL_2": 1}),
    )
    with pytest.raises(ValueError, match="dependency-level claims"):
        verify_slsa_vsa(
            envelope=dependencies_claimed,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )


def test_multiple_build_track_levels_are_rejected() -> None:
    envelope = _mutate(
        _envelope(),
        lambda doc: doc["predicate"].__setitem__(
            "verifiedLevels",
            ["SLSA_BUILD_LEVEL_1", "SLSA_BUILD_LEVEL_2"],
        ),
    )
    with pytest.raises(ValueError, match="exactly one highest Build-track level"):
        verify_slsa_vsa(
            envelope=envelope,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )


def test_expected_input_provenance_and_growth_context_are_bound() -> None:
    missing_input = _mutate(
        _envelope(),
        lambda doc: doc["predicate"].__setitem__("inputAttestations", []),
    )
    with pytest.raises(ValueError, match="inputAttestations"):
        verify_slsa_vsa(
            envelope=missing_input,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )

    wrong_commit = _mutate(
        _envelope(),
        lambda doc: doc["predicate"][GROWTHEVO_VSA_EXTENSION_V1].__setitem__(
            "sourceCommitSha", "e" * 40
        ),
    )
    with pytest.raises(ValueError, match="source commit"):
        verify_slsa_vsa(
            envelope=wrong_commit,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )


def test_unknown_vsa_fields_are_ignored_per_slsa_v1_parsing_rules() -> None:
    envelope = _mutate(
        _envelope(),
        lambda doc: doc["predicate"].__setitem__("https://example.extension/future", {"v": 1}),
    )
    verified = verify_slsa_vsa(
        envelope=envelope,
        expected_artifact=_artifact(),
        policy=_consumer_policy(),
        verifier=FakeVerifier(),
    )
    assert verified.verified_build_level == 2


def test_cross_commit_replay_is_rejected_when_converting_to_promotion_authority() -> None:
    verified_vsa = verify_slsa_vsa(
        envelope=_envelope(),
        expected_artifact=_artifact(),
        policy=_consumer_policy(),
        verifier=FakeVerifier(),
    )
    with pytest.raises(ValueError, match="source commit"):
        verified_vsa.to_delegated_authority_evidence(
            subject=_subject("e" * 40),
            authority_id="delegated_supply_chain",
            authorized_transitions=(PromotionTransition.FINAL_PROMOTION,),
            evidence_epoch=7,
            minimum_build_level=2,
        )


def test_duplicate_json_keys_fail_before_any_trust_decision() -> None:
    envelope = DSSEEnvelope.from_payload(
        payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
        payload=b'{"_type":"https://in-toto.io/Statement/v1","_type":"duplicate"}',
        signatures=(DSSESignature(keyid="fake", sig="c2ln"),),
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        verify_slsa_vsa(
            envelope=envelope,
            expected_artifact=_artifact(),
            policy=_consumer_policy(),
            verifier=FakeVerifier(),
        )
