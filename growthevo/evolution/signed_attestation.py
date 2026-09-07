from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import asdict, dataclass
from hashlib import blake2b
import json
from typing import Mapping, Protocol, Sequence

from .promotion_manifest import (
    AuthorityEvidence,
    AuthorityVerdict,
    PromotionSubject,
    PromotionTransition,
)


IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"
IN_TOTO_DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"
GROWTHEVO_AUTHORITY_PREDICATE_V1 = (
    "https://github.com/jiaweine/GrowthEvo-Harness/attestation/promotion-authority/v1"
)
_SUBJECT_NAME = "growthevo-promotion-subject"


def _canonical_json(payload: Mapping[str, object]) -> bytes:
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


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding.

    PAE = "DSSEv1" SP len(type) SP type SP len(payload) SP payload.
    Lengths are decimal byte lengths as required by DSSE.
    """

    _nonempty(payload_type, "payload_type")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 " + str(len(type_bytes)).encode("ascii") + b" " + type_bytes + b" " + str(
        len(payload)
    ).encode("ascii") + b" " + payload


@dataclass(frozen=True, slots=True)
class DSSESignature:
    keyid: str
    sig: str

    def __post_init__(self) -> None:
        if not isinstance(self.keyid, str):
            raise ValueError("keyid must be a string")
        _nonempty(self.sig, "sig")
        try:
            decoded = b64decode(self.sig, validate=True)
        except (Base64Error, ValueError) as exc:
            raise ValueError("sig must be valid base64") from exc
        if not decoded:
            raise ValueError("sig cannot decode to empty bytes")


@dataclass(frozen=True, slots=True)
class DSSEEnvelope:
    payload_type: str
    payload: str
    signatures: tuple[DSSESignature, ...]

    def __post_init__(self) -> None:
        _nonempty(self.payload_type, "payload_type")
        _nonempty(self.payload, "payload")
        if not self.signatures:
            raise ValueError("DSSE envelope requires at least one signature")
        try:
            decoded = b64decode(self.payload, validate=True)
        except (Base64Error, ValueError) as exc:
            raise ValueError("payload must be valid base64") from exc
        if not decoded:
            raise ValueError("payload cannot decode to empty bytes")

    @classmethod
    def from_payload(
        cls,
        *,
        payload_type: str,
        payload: bytes,
        signatures: Sequence[DSSESignature],
    ) -> "DSSEEnvelope":
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("payload must be non-empty bytes")
        return cls(
            payload_type=payload_type,
            payload=b64encode(payload).decode("ascii"),
            signatures=tuple(signatures),
        )

    @property
    def payload_bytes(self) -> bytes:
        return b64decode(self.payload, validate=True)

    @property
    def pae(self) -> bytes:
        return dsse_pae(self.payload_type, self.payload_bytes)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.dsse-envelope-reference.v1",
                "payloadType": self.payload_type,
                "payload": self.payload,
                "signatures": [asdict(item) for item in self.signatures],
            },
            digest_size=32,
        )


@dataclass(frozen=True, slots=True)
class AuthorityAttestationClaims:
    authority_id: str
    evidence_type: str
    protocol_fingerprint: str
    artifact_fingerprint: str
    verdict: AuthorityVerdict
    authorized_transitions: tuple[PromotionTransition, ...]
    evidence_epoch: int
    source_chain_head: str = "not_applicable"
    details_fingerprint: str = "not_applicable"

    def __post_init__(self) -> None:
        for name in (
            "authority_id",
            "evidence_type",
            "protocol_fingerprint",
            "artifact_fingerprint",
            "source_chain_head",
            "details_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        if not self.authorized_transitions:
            raise ValueError("authorized_transitions cannot be empty")
        if tuple(dict.fromkeys(self.authorized_transitions)) != self.authorized_transitions:
            raise ValueError("authorized_transitions must be unique and ordered")
        if (
            isinstance(self.evidence_epoch, bool)
            or not isinstance(self.evidence_epoch, int)
            or self.evidence_epoch < 0
        ):
            raise ValueError("evidence_epoch must be a non-negative integer")

    def statement_payload(self, subject: PromotionSubject) -> dict[str, object]:
        return {
            "_type": IN_TOTO_STATEMENT_V1,
            "subject": [
                {
                    "name": _SUBJECT_NAME,
                    "digest": {"blake2b-160": subject.fingerprint},
                }
            ],
            "predicateType": GROWTHEVO_AUTHORITY_PREDICATE_V1,
            "predicate": {
                "authority_id": self.authority_id,
                "evidence_type": self.evidence_type,
                "subject_fingerprint": subject.fingerprint,
                "protocol_fingerprint": self.protocol_fingerprint,
                "artifact_fingerprint": self.artifact_fingerprint,
                "verdict": self.verdict.value,
                "authorized_transitions": [item.value for item in self.authorized_transitions],
                "evidence_epoch": self.evidence_epoch,
                "source_chain_head": self.source_chain_head,
                "details_fingerprint": self.details_fingerprint,
            },
        }

    def canonical_statement_bytes(self, subject: PromotionSubject) -> bytes:
        return _canonical_json(self.statement_payload(subject))


@dataclass(frozen=True, slots=True)
class SignatureVerificationResult:
    """Receipt returned only after a trusted verifier validates the DSSE envelope.

    GrowthEvo intentionally does not implement signature algorithms here. A verifier
    adapter is the cryptographic trust boundary and may be backed by Sigstore,
    enterprise PKI/KMS, or another reviewed implementation.
    """

    verifier_id: str
    signer_identity: str
    issuer: str
    verification_material_fingerprint: str
    verified_signature_count: int = 1
    transparency_log_verified: bool = False
    timestamp_verified: bool = False
    transparency_log_entry_fingerprint: str = "not_available"
    timestamp_fingerprint: str = "not_available"

    def __post_init__(self) -> None:
        for name in (
            "verifier_id",
            "signer_identity",
            "issuer",
            "verification_material_fingerprint",
            "transparency_log_entry_fingerprint",
            "timestamp_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        if (
            isinstance(self.verified_signature_count, bool)
            or not isinstance(self.verified_signature_count, int)
            or self.verified_signature_count <= 0
        ):
            raise ValueError("verified_signature_count must be a positive integer")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.signature-verification-result.v1",
                **asdict(self),
            },
            digest_size=32,
        )


class AttestationVerifier(Protocol):
    """Cryptographic verification boundary for a DSSE envelope."""

    verifier_id: str

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        """Verify signature/identity material and return a verified receipt."""


@dataclass(frozen=True, slots=True)
class AuthoritySignerRule:
    authority_id: str
    allowed_signer_identities: tuple[str, ...]
    allowed_issuers: tuple[str, ...]
    allowed_verifier_ids: tuple[str, ...]
    require_transparency_log: bool = True
    require_timestamp: bool = True

    def __post_init__(self) -> None:
        _nonempty(self.authority_id, "authority_id")
        for name, values in (
            ("allowed_signer_identities", self.allowed_signer_identities),
            ("allowed_issuers", self.allowed_issuers),
            ("allowed_verifier_ids", self.allowed_verifier_ids),
        ):
            if not values:
                raise ValueError(f"{name} cannot be empty")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique values")
            for value in values:
                _nonempty(value, name)


@dataclass(frozen=True, slots=True)
class SignedAttestationPolicy:
    policy_id: str
    signer_rules: tuple[AuthoritySignerRule, ...]
    allowed_payload_types: tuple[str, ...] = (IN_TOTO_DSSE_PAYLOAD_TYPE,)
    statement_type: str = IN_TOTO_STATEMENT_V1
    predicate_type: str = GROWTHEVO_AUTHORITY_PREDICATE_V1

    def __post_init__(self) -> None:
        _nonempty(self.policy_id, "policy_id")
        if not self.signer_rules:
            raise ValueError("signer_rules cannot be empty")
        ids = [item.authority_id for item in self.signer_rules]
        if len(set(ids)) != len(ids):
            raise ValueError("each authority can have only one signer rule")
        if not self.allowed_payload_types:
            raise ValueError("allowed_payload_types cannot be empty")
        for value in self.allowed_payload_types:
            _nonempty(value, "allowed_payload_types")
        _nonempty(self.statement_type, "statement_type")
        _nonempty(self.predicate_type, "predicate_type")

    def rule_for(self, authority_id: str) -> AuthoritySignerRule:
        for rule in self.signer_rules:
            if rule.authority_id == authority_id:
                return rule
        raise ValueError("authority has no signed-attestation trust rule")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.signed-attestation-policy.v1",
                "policy_id": self.policy_id,
                "signer_rules": [asdict(item) for item in self.signer_rules],
                "allowed_payload_types": list(self.allowed_payload_types),
                "statement_type": self.statement_type,
                "predicate_type": self.predicate_type,
                "identity_match": "exact",
                "issuer_match": "exact",
                "verifier_match": "exact",
            }
        )


@dataclass(frozen=True, slots=True)
class VerifiedAuthorityAttestation:
    evidence: AuthorityEvidence
    statement_fingerprint: str
    envelope_fingerprint: str
    verification_result_fingerprint: str
    attestation_policy_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.verified-authority-attestation.v1",
                "evidence_fingerprint": self.evidence.fingerprint,
                "statement_fingerprint": self.statement_fingerprint,
                "envelope_fingerprint": self.envelope_fingerprint,
                "verification_result_fingerprint": self.verification_result_fingerprint,
                "attestation_policy_fingerprint": self.attestation_policy_fingerprint,
            },
            digest_size=32,
        )


def _strict_mapping(value: object, *, name: str, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if set(value) != keys:
        raise ValueError(f"{name} has unexpected or missing fields")
    return value


def _parse_statement(
    payload: bytes,
    *,
    expected_subject: PromotionSubject,
    policy: SignedAttestationPolicy,
) -> AuthorityAttestationClaims:
    try:
        decoded = payload.decode("utf-8")
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("attestation payload must be valid UTF-8 JSON") from exc

    statement = _strict_mapping(
        document,
        name="statement",
        keys={"_type", "subject", "predicateType", "predicate"},
    )
    if statement["_type"] != policy.statement_type:
        raise ValueError("unapproved in-toto statement type")
    if statement["predicateType"] != policy.predicate_type:
        raise ValueError("unapproved attestation predicate type")

    subjects = statement["subject"]
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("attestation must contain exactly one subject")
    subject_item = _strict_mapping(
        subjects[0],
        name="subject",
        keys={"name", "digest"},
    )
    if subject_item["name"] != _SUBJECT_NAME:
        raise ValueError("attestation subject name is not GrowthEvo promotion subject")
    digest = _strict_mapping(
        subject_item["digest"],
        name="subject.digest",
        keys={"blake2b-160"},
    )
    if digest["blake2b-160"] != expected_subject.fingerprint:
        raise ValueError("attestation subject digest does not match promotion subject")

    predicate = _strict_mapping(
        statement["predicate"],
        name="predicate",
        keys={
            "authority_id",
            "evidence_type",
            "subject_fingerprint",
            "protocol_fingerprint",
            "artifact_fingerprint",
            "verdict",
            "authorized_transitions",
            "evidence_epoch",
            "source_chain_head",
            "details_fingerprint",
        },
    )
    if predicate["subject_fingerprint"] != expected_subject.fingerprint:
        raise ValueError("predicate subject fingerprint does not match promotion subject")

    transitions_raw = predicate["authorized_transitions"]
    if not isinstance(transitions_raw, list) or not transitions_raw:
        raise ValueError("authorized_transitions must be a non-empty array")
    try:
        transitions = tuple(PromotionTransition(item) for item in transitions_raw)
        verdict = AuthorityVerdict(predicate["verdict"])
    except (TypeError, ValueError) as exc:
        raise ValueError("attestation contains an invalid enum value") from exc

    return AuthorityAttestationClaims(
        authority_id=str(predicate["authority_id"]),
        evidence_type=str(predicate["evidence_type"]),
        protocol_fingerprint=str(predicate["protocol_fingerprint"]),
        artifact_fingerprint=str(predicate["artifact_fingerprint"]),
        verdict=verdict,
        authorized_transitions=transitions,
        evidence_epoch=predicate["evidence_epoch"],  # type: ignore[arg-type]
        source_chain_head=str(predicate["source_chain_head"]),
        details_fingerprint=str(predicate["details_fingerprint"]),
    )


def verify_authority_attestation(
    *,
    envelope: DSSEEnvelope,
    expected_subject: PromotionSubject,
    policy: SignedAttestationPolicy,
    verifier: AttestationVerifier,
) -> VerifiedAuthorityAttestation:
    """Verify a signed authority statement and translate it into Phase-14 evidence.

    Parsing the untrusted payload may occur before signature verification only to
    select the exact pre-registered authority trust rule. No claim is accepted or
    emitted until the verifier succeeds and every identity/provenance check passes.
    """

    if envelope.payload_type not in policy.allowed_payload_types:
        raise ValueError("unapproved DSSE payload type")

    claims = _parse_statement(
        envelope.payload_bytes,
        expected_subject=expected_subject,
        policy=policy,
    )
    rule = policy.rule_for(claims.authority_id)
    declared_verifier_id = _nonempty(getattr(verifier, "verifier_id", ""), "verifier.verifier_id")
    if declared_verifier_id not in rule.allowed_verifier_ids:
        raise ValueError("attestation verifier is not approved for this authority")

    verification = verifier.verify(envelope)
    if verification.verifier_id != declared_verifier_id:
        raise ValueError("verification receipt verifier id does not match verifier")
    if verification.verifier_id not in rule.allowed_verifier_ids:
        raise ValueError("verification receipt uses an unapproved verifier")
    if verification.signer_identity not in rule.allowed_signer_identities:
        raise ValueError("signer identity is not approved for this authority")
    if verification.issuer not in rule.allowed_issuers:
        raise ValueError("signer issuer is not approved for this authority")
    if rule.require_transparency_log and not verification.transparency_log_verified:
        raise ValueError("transparency-log verification is required")
    if rule.require_timestamp and not verification.timestamp_verified:
        raise ValueError("trusted timestamp verification is required")

    try:
        canonical_document = json.loads(envelope.payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover - parsed above
        raise ValueError("attestation payload must be valid UTF-8 JSON") from exc
    statement_fingerprint = _fingerprint(
        {
            "schema": "growthevo.in-toto-authority-statement.v1",
            "statement": canonical_document,
        },
        digest_size=32,
    )
    verified_details = _fingerprint(
        {
            "schema": "growthevo.verified-attestation-details.v1",
            "claimed_details_fingerprint": claims.details_fingerprint,
            "statement_fingerprint": statement_fingerprint,
            "envelope_fingerprint": envelope.fingerprint,
            "verification_result_fingerprint": verification.fingerprint,
            "attestation_policy_fingerprint": policy.fingerprint,
        },
        digest_size=32,
    )

    evidence = AuthorityEvidence(
        authority_id=claims.authority_id,
        evidence_type=claims.evidence_type,
        producer=verification.signer_identity,
        subject_fingerprint=expected_subject.fingerprint,
        protocol_fingerprint=claims.protocol_fingerprint,
        artifact_fingerprint=claims.artifact_fingerprint,
        verdict=claims.verdict,
        authorized_transitions=claims.authorized_transitions,
        evidence_epoch=claims.evidence_epoch,
        source_chain_head=claims.source_chain_head,
        details_fingerprint=verified_details,
    )
    return VerifiedAuthorityAttestation(
        evidence=evidence,
        statement_fingerprint=statement_fingerprint,
        envelope_fingerprint=envelope.fingerprint,
        verification_result_fingerprint=verification.fingerprint,
        attestation_policy_fingerprint=policy.fingerprint,
    )
