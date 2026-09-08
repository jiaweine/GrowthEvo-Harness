from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b, sha256
import json
from typing import Mapping, Protocol, Sequence

from .promotion_manifest import (
    AuthorityEvidence,
    AuthorityVerdict,
    PromotionSubject,
    PromotionTransition,
)
from .signed_attestation import (
    AttestationVerifier,
    DSSEEnvelope,
    IN_TOTO_DSSE_PAYLOAD_TYPE,
    IN_TOTO_STATEMENT_V1,
)
from .slsa_build_provenance import VerifiedSLSABuildProvenance


SLSA_VSA_V1 = "https://slsa.dev/verification_summary/v1"
SLSA_VERSION_1_2 = "1.2"
GROWTHEVO_VSA_EXTENSION_V1 = (
    "https://github.com/jiaweine/GrowthEvo-Harness/attestation/slsa-vsa-context/v1"
)


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(payload: Mapping[str, object], *, digest_size: int = 20) -> str:
    return blake2b(_canonical_json(payload), digest_size=digest_size).hexdigest()


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a SHA-256 hex string")
    normalized = value.lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex string")
    return normalized


def _commit_sha(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hexadecimal commit SHA")
    normalized = value.lower()
    if len(normalized) < 7 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{name} must be a hexadecimal commit SHA")
    return normalized


def _reject_duplicate_keys(raw: bytes) -> object:
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("VSA payload must be non-empty bytes")

    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=hook)
    except UnicodeDecodeError as exc:
        raise ValueError("VSA payload must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("VSA payload must be valid JSON") from exc


@dataclass(frozen=True, slots=True)
class VSAResourceDescriptor:
    uri: str
    sha256: str

    def __post_init__(self) -> None:
        _nonempty(self.uri, "uri")
        object.__setattr__(self, "sha256", _sha256_hex(self.sha256, "sha256"))

    def payload(self) -> dict[str, object]:
        return {"uri": self.uri, "digest": {"sha256": self.sha256}}

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.vsa-resource-descriptor.v1",
                "uri": self.uri,
                "sha256": self.sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class SLSAVSAProductionSpec:
    verifier_id: str
    resource_uri: str
    policy: VSAResourceDescriptor
    provenance_uri: str
    build_level: int
    verifier_versions: tuple[tuple[str, str], ...] = ()
    additional_input_attestations: tuple[VSAResourceDescriptor, ...] = ()
    slsa_version: str = SLSA_VERSION_1_2
    time_verified: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.verifier_id, "verifier_id")
        _nonempty(self.resource_uri, "resource_uri")
        _nonempty(self.provenance_uri, "provenance_uri")
        if (
            isinstance(self.build_level, bool)
            or not isinstance(self.build_level, int)
            or not 1 <= self.build_level <= 3
        ):
            raise ValueError("build_level must be an integer from 1 through 3")
        if len(set(name for name, _ in self.verifier_versions)) != len(self.verifier_versions):
            raise ValueError("verifier_versions component names must be unique")
        for name, version in self.verifier_versions:
            _nonempty(name, "verifier_versions component")
            _nonempty(version, "verifier_versions version")
        if len(set(item.fingerprint for item in self.additional_input_attestations)) != len(
            self.additional_input_attestations
        ):
            raise ValueError("additional_input_attestations must be unique")
        _nonempty(self.slsa_version, "slsa_version")
        if self.time_verified is not None:
            _nonempty(self.time_verified, "time_verified")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.slsa-vsa-production-spec.v1",
                "verifier_id": self.verifier_id,
                "resource_uri": self.resource_uri,
                "policy_fingerprint": self.policy.fingerprint,
                "provenance_uri": self.provenance_uri,
                "build_level": self.build_level,
                "verifier_versions": [list(item) for item in self.verifier_versions],
                "additional_input_attestations": [
                    item.fingerprint for item in self.additional_input_attestations
                ],
                "slsa_version": self.slsa_version,
                "time_verified": self.time_verified,
                "dependency_claim": "none",
            }
        )


@dataclass(frozen=True, slots=True)
class ProducedSLSAVSA:
    statement_bytes: bytes
    statement_fingerprint: str
    subject_sha256: str
    resource_uri: str
    verifier_id: str
    verified_build_level: int
    source_commit_sha: str
    source_verification_fingerprint: str
    production_spec_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.statement_bytes, bytes) or not self.statement_bytes:
            raise ValueError("statement_bytes must be non-empty bytes")
        for name in (
            "statement_fingerprint",
            "resource_uri",
            "verifier_id",
            "source_verification_fingerprint",
            "production_spec_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        object.__setattr__(
            self,
            "subject_sha256",
            _sha256_hex(self.subject_sha256, "subject_sha256"),
        )
        object.__setattr__(
            self,
            "source_commit_sha",
            _commit_sha(self.source_commit_sha, "source_commit_sha"),
        )
        if (
            isinstance(self.verified_build_level, bool)
            or not isinstance(self.verified_build_level, int)
            or not 1 <= self.verified_build_level <= 3
        ):
            raise ValueError("verified_build_level must be an integer from 1 through 3")


class VSAEnvelopeSigner(Protocol):
    signer_id: str

    def sign(self, *, payload_type: str, payload: bytes) -> DSSEEnvelope:
        """Sign the canonical VSA statement and return a DSSE envelope."""


def produce_slsa_vsa(
    *,
    verified_provenance: VerifiedSLSABuildProvenance,
    spec: SLSAVSAProductionSpec,
) -> ProducedSLSAVSA:
    if spec.build_level > verified_provenance.trusted_build_level:
        raise ValueError("VSA cannot claim a Build level above the verified local trust level")

    provenance_descriptor = VSAResourceDescriptor(
        uri=spec.provenance_uri,
        sha256=verified_provenance.provenance_fingerprint,
    )
    inputs = (provenance_descriptor, *spec.additional_input_attestations)
    if len(set(item.fingerprint for item in inputs)) != len(inputs):
        raise ValueError("inputAttestations contain duplicate resource descriptors")

    verifier_payload: dict[str, object] = {"id": spec.verifier_id}
    if spec.verifier_versions:
        verifier_payload["version"] = {
            name: version for name, version in spec.verifier_versions
        }

    predicate: dict[str, object] = {
        "verifier": verifier_payload,
        "resourceUri": spec.resource_uri,
        "policy": spec.policy.payload(),
        "inputAttestations": [item.payload() for item in inputs],
        "verificationResult": "PASSED",
        "verifiedLevels": [f"SLSA_BUILD_LEVEL_{spec.build_level}"],
        "dependencyLevels": None,
        "slsaVersion": spec.slsa_version,
        GROWTHEVO_VSA_EXTENSION_V1: {
            "sourceCommitSha": verified_provenance.source_commit_sha,
            "sourceDependencyUri": verified_provenance.source_dependency_uri,
            "sourceVerificationFingerprint": verified_provenance.fingerprint,
            "buildExpectationFingerprint": verified_provenance.expectation_fingerprint,
            "verifiedProvenanceFingerprint": verified_provenance.provenance_fingerprint,
        },
    }
    if spec.time_verified is not None:
        predicate["timeVerified"] = spec.time_verified

    statement = {
        "_type": IN_TOTO_STATEMENT_V1,
        "subject": [
            {
                "name": verified_provenance.distribution_filename,
                "digest": {"sha256": verified_provenance.distribution_sha256},
            }
        ],
        "predicateType": SLSA_VSA_V1,
        "predicate": predicate,
    }
    statement_bytes = _canonical_json(statement)
    return ProducedSLSAVSA(
        statement_bytes=statement_bytes,
        statement_fingerprint=sha256(statement_bytes).hexdigest(),
        subject_sha256=verified_provenance.distribution_sha256,
        resource_uri=spec.resource_uri,
        verifier_id=spec.verifier_id,
        verified_build_level=spec.build_level,
        source_commit_sha=verified_provenance.source_commit_sha,
        source_verification_fingerprint=verified_provenance.fingerprint,
        production_spec_fingerprint=spec.fingerprint,
    )


def sign_slsa_vsa(*, produced: ProducedSLSAVSA, signer: VSAEnvelopeSigner) -> DSSEEnvelope:
    _nonempty(getattr(signer, "signer_id", ""), "signer.signer_id")
    envelope = signer.sign(
        payload_type=IN_TOTO_DSSE_PAYLOAD_TYPE,
        payload=produced.statement_bytes,
    )
    if envelope.payload_type != IN_TOTO_DSSE_PAYLOAD_TYPE:
        raise ValueError("VSA signer returned an unexpected DSSE payload type")
    if envelope.payload_bytes != produced.statement_bytes:
        raise ValueError("VSA signer returned an envelope for different payload bytes")
    return envelope


@dataclass(frozen=True, slots=True)
class VSAVerifierTrust:
    verifier_id: str
    allowed_signer_identities: tuple[str, ...]
    allowed_issuers: tuple[str, ...]
    allowed_attestation_verifier_ids: tuple[str, ...]
    maximum_build_level: int = 3
    require_transparency_log: bool = True
    require_timestamp: bool = True

    def __post_init__(self) -> None:
        _nonempty(self.verifier_id, "verifier_id")
        for name, values in (
            ("allowed_signer_identities", self.allowed_signer_identities),
            ("allowed_issuers", self.allowed_issuers),
            ("allowed_attestation_verifier_ids", self.allowed_attestation_verifier_ids),
        ):
            if not values:
                raise ValueError(f"{name} cannot be empty")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
            for value in values:
                _nonempty(value, name)
        if (
            isinstance(self.maximum_build_level, bool)
            or not isinstance(self.maximum_build_level, int)
            or not 1 <= self.maximum_build_level <= 3
        ):
            raise ValueError("maximum_build_level must be an integer from 1 through 3")


@dataclass(frozen=True, slots=True)
class SLSAVSAConsumerPolicy:
    policy_id: str
    trusted_verifiers: tuple[VSAVerifierTrust, ...]
    expected_policy_uri: str
    allowed_policy_sha256s: tuple[str, ...]
    minimum_build_level: int = 2
    allowed_slsa_versions: tuple[str, ...] = (SLSA_VERSION_1_2,)
    require_dependency_levels_unclaimed: bool = True
    require_input_attestations: bool = True
    require_growthevo_extension: bool = True

    def __post_init__(self) -> None:
        _nonempty(self.policy_id, "policy_id")
        if not self.trusted_verifiers:
            raise ValueError("trusted_verifiers cannot be empty")
        ids = [item.verifier_id for item in self.trusted_verifiers]
        if len(set(ids)) != len(ids):
            raise ValueError("trusted_verifiers may contain each verifier_id only once")
        _nonempty(self.expected_policy_uri, "expected_policy_uri")
        if not self.allowed_policy_sha256s:
            raise ValueError("allowed_policy_sha256s cannot be empty")
        normalized = tuple(
            _sha256_hex(value, "allowed_policy_sha256s")
            for value in self.allowed_policy_sha256s
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_policy_sha256s must be unique")
        object.__setattr__(self, "allowed_policy_sha256s", normalized)
        if (
            isinstance(self.minimum_build_level, bool)
            or not isinstance(self.minimum_build_level, int)
            or not 1 <= self.minimum_build_level <= 3
        ):
            raise ValueError("minimum_build_level must be an integer from 1 through 3")
        if not self.allowed_slsa_versions:
            raise ValueError("allowed_slsa_versions cannot be empty")
        for value in self.allowed_slsa_versions:
            _nonempty(value, "allowed_slsa_versions")

    def trust_for(self, verifier_id: str) -> VSAVerifierTrust:
        for trust in self.trusted_verifiers:
            if trust.verifier_id == verifier_id:
                return trust
        raise ValueError("VSA verifier.id is not trusted by consumer policy")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.slsa-vsa-consumer-policy.v1",
                "policy_id": self.policy_id,
                "trusted_verifiers": [asdict(item) for item in self.trusted_verifiers],
                "expected_policy_uri": self.expected_policy_uri,
                "allowed_policy_sha256s": list(self.allowed_policy_sha256s),
                "minimum_build_level": self.minimum_build_level,
                "allowed_slsa_versions": list(self.allowed_slsa_versions),
                "require_dependency_levels_unclaimed": self.require_dependency_levels_unclaimed,
                "require_input_attestations": self.require_input_attestations,
                "require_growthevo_extension": self.require_growthevo_extension,
                "signer_verifier_pairing": "exact",
                "unknown_vsa_fields": "ignored_per_slsa_v1",
            }
        )


@dataclass(frozen=True, slots=True)
class VSAArtifactIdentity:
    name: str
    sha256: str
    resource_uri: str
    expected_source_commit_sha: str
    expected_source_verification_fingerprint: str
    expected_input_attestation_sha256: str

    def __post_init__(self) -> None:
        _nonempty(self.name, "name")
        object.__setattr__(self, "sha256", _sha256_hex(self.sha256, "sha256"))
        _nonempty(self.resource_uri, "resource_uri")
        object.__setattr__(
            self,
            "expected_source_commit_sha",
            _commit_sha(self.expected_source_commit_sha, "expected_source_commit_sha"),
        )
        _nonempty(
            self.expected_source_verification_fingerprint,
            "expected_source_verification_fingerprint",
        )
        object.__setattr__(
            self,
            "expected_input_attestation_sha256",
            _sha256_hex(
                self.expected_input_attestation_sha256,
                "expected_input_attestation_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class VerifiedSLSAVSA:
    artifact_name: str
    artifact_sha256: str
    resource_uri: str
    verifier_id: str
    signer_identity: str
    issuer: str
    verified_build_level: int
    policy_uri: str
    policy_sha256: str
    source_commit_sha: str
    source_verification_fingerprint: str
    input_attestations_fingerprint: str
    statement_fingerprint: str
    envelope_fingerprint: str
    verification_result_fingerprint: str
    consumer_policy_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.verified-slsa-vsa.v1",
                **asdict(self),
            },
            digest_size=32,
        )

    def to_delegated_authority_evidence(
        self,
        *,
        subject: PromotionSubject,
        authority_id: str,
        authorized_transitions: Sequence[PromotionTransition],
        evidence_epoch: int,
        minimum_build_level: int,
    ) -> AuthorityEvidence:
        _nonempty(authority_id, "authority_id")
        if _commit_sha(subject.commit_sha, "subject.commit_sha") != self.source_commit_sha:
            raise ValueError("VSA source commit does not match promotion subject")
        if (
            isinstance(minimum_build_level, bool)
            or not isinstance(minimum_build_level, int)
            or not 1 <= minimum_build_level <= 3
        ):
            raise ValueError("minimum_build_level must be an integer from 1 through 3")
        if self.verified_build_level < minimum_build_level:
            raise ValueError("VSA does not establish the required SLSA Build level")
        transitions = tuple(authorized_transitions)
        if not transitions:
            raise ValueError("authorized_transitions cannot be empty")
        return AuthorityEvidence(
            authority_id=authority_id,
            evidence_type="slsa_vsa_delegated_verification.v1",
            producer=self.verifier_id,
            subject_fingerprint=subject.fingerprint,
            protocol_fingerprint=self.consumer_policy_fingerprint,
            artifact_fingerprint=self.fingerprint,
            verdict=AuthorityVerdict.SATISFIED,
            authorized_transitions=transitions,
            evidence_epoch=evidence_epoch,
            source_chain_head=self.verification_result_fingerprint,
            details_fingerprint=self.fingerprint,
        )


def _require_object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _parse_build_level(levels: object) -> int:
    if not isinstance(levels, list) or not levels:
        raise ValueError("verifiedLevels must be a non-empty array")
    build_levels: list[int] = []
    for value in levels:
        if not isinstance(value, str):
            raise ValueError("verifiedLevels entries must be strings")
        prefix = "SLSA_BUILD_LEVEL_"
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix) :]
        if suffix == "UNEVALUATED":
            build_levels.append(0)
            continue
        if suffix not in {"0", "1", "2", "3"}:
            raise ValueError("unsupported SLSA Build level")
        build_levels.append(int(suffix))
    if len(build_levels) != 1:
        raise ValueError("VSA must contain exactly one highest Build-track level")
    return build_levels[0]


def verify_slsa_vsa(
    *,
    envelope: DSSEEnvelope,
    expected_artifact: VSAArtifactIdentity,
    policy: SLSAVSAConsumerPolicy,
    verifier: AttestationVerifier,
) -> VerifiedSLSAVSA:
    if envelope.payload_type != IN_TOTO_DSSE_PAYLOAD_TYPE:
        raise ValueError("unapproved VSA DSSE payload type")

    document = _reject_duplicate_keys(envelope.payload_bytes)
    statement = _require_object(document, "statement")
    if statement.get("_type") != IN_TOTO_STATEMENT_V1:
        raise ValueError("VSA has an unexpected in-toto statement type")
    if statement.get("predicateType") != SLSA_VSA_V1:
        raise ValueError("VSA has an unexpected predicateType")

    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("GrowthEvo VSA consumer requires exactly one subject")
    subject = _require_object(subjects[0], "subject")
    if subject.get("name") != expected_artifact.name:
        raise ValueError("VSA subject name does not match artifact")
    digest = _require_object(subject.get("digest"), "subject.digest")
    if digest.get("sha256") != expected_artifact.sha256:
        raise ValueError("VSA subject SHA-256 does not match artifact")

    predicate = _require_object(statement.get("predicate"), "predicate")
    verifier_object = _require_object(predicate.get("verifier"), "predicate.verifier")
    verifier_id = _require_string(verifier_object.get("id"), "predicate.verifier.id")
    trust = policy.trust_for(verifier_id)

    declared_verifier_id = _nonempty(
        getattr(verifier, "verifier_id", ""),
        "verifier.verifier_id",
    )
    if declared_verifier_id not in trust.allowed_attestation_verifier_ids:
        raise ValueError("cryptographic VSA verifier is not approved for verifier.id")

    verification = verifier.verify(envelope)
    if verification.verifier_id != declared_verifier_id:
        raise ValueError("VSA verification receipt verifier id does not match verifier")
    if verification.verifier_id not in trust.allowed_attestation_verifier_ids:
        raise ValueError("VSA verification receipt uses an unapproved verifier")
    if verification.signer_identity not in trust.allowed_signer_identities:
        raise ValueError("VSA signer identity is not approved for verifier.id")
    if verification.issuer not in trust.allowed_issuers:
        raise ValueError("VSA signer issuer is not approved for verifier.id")
    if trust.require_transparency_log and not verification.transparency_log_verified:
        raise ValueError("VSA transparency-log verification is required")
    if trust.require_timestamp and not verification.timestamp_verified:
        raise ValueError("VSA trusted timestamp verification is required")

    resource_uri = _require_string(predicate.get("resourceUri"), "predicate.resourceUri")
    if resource_uri != expected_artifact.resource_uri:
        raise ValueError("VSA resourceUri does not match expected artifact resource")

    if predicate.get("verificationResult") != "PASSED":
        raise ValueError("VSA verificationResult is not PASSED")

    build_level = _parse_build_level(predicate.get("verifiedLevels"))
    if build_level < policy.minimum_build_level:
        raise ValueError("VSA does not establish the consumer's minimum Build level")
    if build_level > trust.maximum_build_level:
        raise ValueError("VSA claims a Build level above this verifier's delegated trust")

    policy_descriptor = _require_object(predicate.get("policy"), "predicate.policy")
    policy_uri = _require_string(policy_descriptor.get("uri"), "predicate.policy.uri")
    if policy_uri != policy.expected_policy_uri:
        raise ValueError("VSA policy URI is not approved")
    policy_digest = _require_object(policy_descriptor.get("digest"), "predicate.policy.digest")
    policy_sha256 = _sha256_hex(
        _require_string(
            policy_digest.get("sha256"),
            "predicate.policy.digest.sha256",
        ),
        "predicate.policy.digest.sha256",
    )
    if policy_sha256 not in policy.allowed_policy_sha256s:
        raise ValueError("VSA policy digest is not approved")

    slsa_version = predicate.get("slsaVersion")
    if slsa_version is not None and slsa_version not in policy.allowed_slsa_versions:
        raise ValueError("VSA slsaVersion is not approved")

    dependency_levels = predicate.get("dependencyLevels")
    if policy.require_dependency_levels_unclaimed and dependency_levels is not None:
        raise ValueError("VSA must not make dependency-level claims under this policy")

    input_attestations = predicate.get("inputAttestations")
    if policy.require_input_attestations:
        if not isinstance(input_attestations, list) or not input_attestations:
            raise ValueError("VSA inputAttestations are required")
    elif input_attestations is None:
        input_attestations = []
    elif not isinstance(input_attestations, list):
        raise ValueError("VSA inputAttestations must be an array")

    expected_input_seen = False
    normalized_inputs: list[dict[str, object]] = []
    for item in input_attestations:
        descriptor = _require_object(item, "inputAttestation")
        uri = _require_string(descriptor.get("uri"), "inputAttestation.uri")
        digest_object = _require_object(descriptor.get("digest"), "inputAttestation.digest")
        digest_sha256 = _sha256_hex(
            _require_string(
                digest_object.get("sha256"),
                "inputAttestation.digest.sha256",
            ),
            "inputAttestation.digest.sha256",
        )
        if digest_sha256 == expected_artifact.expected_input_attestation_sha256:
            expected_input_seen = True
        normalized_inputs.append({"uri": uri, "digest": {"sha256": digest_sha256}})
    if policy.require_input_attestations and not expected_input_seen:
        raise ValueError("VSA does not bind the expected input provenance digest")

    extension = predicate.get(GROWTHEVO_VSA_EXTENSION_V1)
    if policy.require_growthevo_extension:
        extension_object = _require_object(extension, "GrowthEvo VSA extension")
        source_commit_sha = _commit_sha(
            _require_string(
                extension_object.get("sourceCommitSha"),
                "extension.sourceCommitSha",
            ),
            "extension.sourceCommitSha",
        )
        if source_commit_sha != expected_artifact.expected_source_commit_sha:
            raise ValueError("VSA source commit does not match expected source commit")
        source_verification_fingerprint = _require_string(
            extension_object.get("sourceVerificationFingerprint"),
            "extension.sourceVerificationFingerprint",
        )
        if (
            source_verification_fingerprint
            != expected_artifact.expected_source_verification_fingerprint
        ):
            raise ValueError("VSA source verification fingerprint does not match expected evidence")
        verified_provenance_fingerprint = _sha256_hex(
            _require_string(
                extension_object.get("verifiedProvenanceFingerprint"),
                "extension.verifiedProvenanceFingerprint",
            ),
            "extension.verifiedProvenanceFingerprint",
        )
        if (
            verified_provenance_fingerprint
            != expected_artifact.expected_input_attestation_sha256
        ):
            raise ValueError("VSA extension provenance fingerprint does not match input provenance")
        _require_string(
            extension_object.get("sourceDependencyUri"),
            "extension.sourceDependencyUri",
        )
        _require_string(
            extension_object.get("buildExpectationFingerprint"),
            "extension.buildExpectationFingerprint",
        )
    else:
        source_commit_sha = expected_artifact.expected_source_commit_sha
        source_verification_fingerprint = (
            expected_artifact.expected_source_verification_fingerprint
        )

    statement_fingerprint = sha256(envelope.payload_bytes).hexdigest()
    input_fingerprint = sha256(_canonical_json(normalized_inputs)).hexdigest()

    return VerifiedSLSAVSA(
        artifact_name=expected_artifact.name,
        artifact_sha256=expected_artifact.sha256,
        resource_uri=resource_uri,
        verifier_id=verifier_id,
        signer_identity=verification.signer_identity,
        issuer=verification.issuer,
        verified_build_level=build_level,
        policy_uri=policy_uri,
        policy_sha256=policy_sha256,
        source_commit_sha=source_commit_sha,
        source_verification_fingerprint=source_verification_fingerprint,
        input_attestations_fingerprint=input_fingerprint,
        statement_fingerprint=statement_fingerprint,
        envelope_fingerprint=envelope.fingerprint,
        verification_result_fingerprint=verification.fingerprint,
        consumer_policy_fingerprint=policy.fingerprint,
    )
