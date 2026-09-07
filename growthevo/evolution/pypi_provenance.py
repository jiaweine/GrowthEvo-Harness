from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b, sha256
import json
from typing import Mapping, Sequence

from .promotion_manifest import (
    AuthorityEvidence,
    AuthorityVerdict,
    PromotionSubject,
    PromotionTransition,
)


PYPI_ATTESTATIONS_VERSION = "0.0.30"
PYPI_PUBLISH_PREDICATE_V1 = "https://docs.pypi.org/attestations/publish/v1"
IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

# Fulcio certificate claims documented by Sigstore and consumed by
# pypi-attestations' GitHub Trusted Publisher policy.
SOURCE_REPOSITORY_URI_OID = "1.3.6.1.4.1.57264.1.12"
SOURCE_REPOSITORY_DIGEST_OID = "1.3.6.1.4.1.57264.1.13"
BUILD_CONFIG_URI_OID = "1.3.6.1.4.1.57264.1.18"


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
        raise ValueError("provenance_json must be non-empty bytes")

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
        raise ValueError("provenance_json must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("provenance_json must be valid JSON") from exc


@dataclass(frozen=True, slots=True)
class PyPIPublishProvenanceSpec:
    """Frozen verification contract for one PyPI distribution and GitHub publisher.

    This is a release-channel provenance contract. A PyPI Publish attestation proves
    that an exact distribution was uploaded through the expected Trusted Publisher;
    it does not by itself prove a reproducible build or source-to-binary equivalence.
    """

    distribution_filename: str
    distribution_sha256: str
    expected_repository: str
    expected_workflow: str
    expected_source_commit_sha: str | None = None
    predicate_type: str = PYPI_PUBLISH_PREDICATE_V1
    pypi_attestations_version: str = PYPI_ATTESTATIONS_VERSION
    offline: bool = True
    max_provenance_bytes: int = 1_000_000
    require_single_transparency_entry: bool = True

    def __post_init__(self) -> None:
        _nonempty(self.distribution_filename, "distribution_filename")
        if "/" in self.distribution_filename or "\\" in self.distribution_filename:
            raise ValueError("distribution_filename must be a basename")
        if not self.distribution_filename.endswith((".whl", ".tar.gz", ".zip")):
            raise ValueError("distribution_filename must be a wheel or source distribution")
        object.__setattr__(
            self,
            "distribution_sha256",
            _sha256_hex(self.distribution_sha256, "distribution_sha256"),
        )
        _nonempty(self.expected_repository, "expected_repository")
        if self.expected_repository.count("/") != 1:
            raise ValueError("expected_repository must be a GitHub owner/repository slug")
        _nonempty(self.expected_workflow, "expected_workflow")
        if "/" in self.expected_workflow or "@" in self.expected_workflow:
            raise ValueError("expected_workflow must be the workflow filename only")
        if self.expected_source_commit_sha is not None:
            object.__setattr__(
                self,
                "expected_source_commit_sha",
                _commit_sha(self.expected_source_commit_sha, "expected_source_commit_sha"),
            )
        _nonempty(self.predicate_type, "predicate_type")
        _nonempty(self.pypi_attestations_version, "pypi_attestations_version")
        if isinstance(self.max_provenance_bytes, bool) or not isinstance(
            self.max_provenance_bytes, int
        ):
            raise ValueError("max_provenance_bytes must be an integer")
        if self.max_provenance_bytes < 1024:
            raise ValueError("max_provenance_bytes must be at least 1024")

    @property
    def publisher_identity(self) -> str:
        return (
            "pypi-trusted-publisher:github:"
            f"{self.expected_repository}:.github/workflows/{self.expected_workflow}"
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.pypi-publish-provenance-spec.v1",
                **asdict(self),
            }
        )


@dataclass(frozen=True, slots=True)
class VerifiedPyPIProvenance:
    distribution_filename: str
    distribution_sha256: str
    publisher_identity: str
    issuer: str
    source_repository_uri: str
    source_repository_digest: str
    build_config_uri: str
    predicate_type: str
    verification_material_fingerprint: str
    transparency_log_fingerprint: str
    provenance_fingerprint: str
    verifier_spec_fingerprint: str
    verified_attestation_count: int

    def __post_init__(self) -> None:
        for name in (
            "distribution_filename",
            "publisher_identity",
            "issuer",
            "source_repository_uri",
            "source_repository_digest",
            "build_config_uri",
            "predicate_type",
            "verification_material_fingerprint",
            "transparency_log_fingerprint",
            "provenance_fingerprint",
            "verifier_spec_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        object.__setattr__(
            self,
            "distribution_sha256",
            _sha256_hex(self.distribution_sha256, "distribution_sha256"),
        )
        object.__setattr__(
            self,
            "source_repository_digest",
            _commit_sha(self.source_repository_digest, "source_repository_digest"),
        )
        if (
            isinstance(self.verified_attestation_count, bool)
            or not isinstance(self.verified_attestation_count, int)
            or self.verified_attestation_count <= 0
        ):
            raise ValueError("verified_attestation_count must be a positive integer")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.verified-pypi-provenance.v1",
                **asdict(self),
            },
            digest_size=32,
        )

    def to_release_authority_evidence(
        self,
        *,
        subject: PromotionSubject,
        authority_id: str,
        authorized_transitions: Sequence[PromotionTransition],
        evidence_epoch: int,
    ) -> AuthorityEvidence:
        """Translate verified release provenance into Phase-14 authority evidence.

        The conversion is intentionally unavailable unless the Fulcio source
        repository digest equals the promotion subject's source commit. This binds
        the external release evidence to the same source revision before policy can
        compose it with the rest of the promotion evidence plane.
        """

        _nonempty(authority_id, "authority_id")
        if _commit_sha(subject.commit_sha, "subject.commit_sha") != self.source_repository_digest:
            raise ValueError("PyPI provenance source commit does not match promotion subject")
        transitions = tuple(authorized_transitions)
        if not transitions:
            raise ValueError("authorized_transitions cannot be empty")
        return AuthorityEvidence(
            authority_id=authority_id,
            evidence_type="pypi_publish_provenance.v1",
            producer=self.publisher_identity,
            subject_fingerprint=subject.fingerprint,
            protocol_fingerprint=self.verifier_spec_fingerprint,
            artifact_fingerprint=self.fingerprint,
            verdict=AuthorityVerdict.SATISFIED,
            authorized_transitions=transitions,
            evidence_epoch=evidence_epoch,
            source_chain_head=self.transparency_log_fingerprint,
            details_fingerprint=self.fingerprint,
        )


class PyPIPublishProvenanceVerifier:
    """Verify a PEP 740 PyPI Publish attestation using pypi-attestations.

    The optional dependency is imported lazily. Verification uses the public
    pypi-attestations models and `Attestation.verify(...)` API. GrowthEvo performs
    additional exact publisher, distribution, predicate, source-commit, JSON and
    provenance-cardinality checks around that cryptographic boundary.
    """

    def __init__(self, *, provenance_json: bytes, spec: PyPIPublishProvenanceSpec) -> None:
        if len(provenance_json) > spec.max_provenance_bytes:
            raise ValueError("provenance_json exceeds preregistered size limit")
        _reject_duplicate_keys(provenance_json)
        self.spec = spec
        self._raw = provenance_json
        self._provenance_sha256 = sha256(provenance_json).hexdigest()

    @property
    def verifier_id(self) -> str:
        return f"pypi-pep740-v1:{self.spec.fingerprint}"

    def verify(self) -> VerifiedPyPIProvenance:
        try:
            import pypi_attestations as pypi_api
        except ImportError as exc:  # pragma: no cover - exercised in dependency-free installs
            raise RuntimeError(
                "PyPI provenance verification requires the optional attestation-pypi extra"
            ) from exc

        if getattr(pypi_api, "__version__", None) != self.spec.pypi_attestations_version:
            raise RuntimeError("installed pypi-attestations version does not match verifier spec")

        try:
            provenance = pypi_api.Provenance.model_validate_json(self._raw)
            distribution = pypi_api.Distribution(
                name=self.spec.distribution_filename,
                digest=self.spec.distribution_sha256,
            )
        except Exception as exc:
            raise ValueError("invalid PEP 740 provenance or distribution contract") from exc

        matching_bundles = []
        for bundle in provenance.attestation_bundles:
            publisher = bundle.publisher
            if not isinstance(publisher, pypi_api.GitHubPublisher):
                continue
            if (
                publisher.repository == self.spec.expected_repository
                and publisher.workflow == self.spec.expected_workflow
            ):
                matching_bundles.append(bundle)

        if len(matching_bundles) != 1:
            raise ValueError("expected exactly one matching GitHub Trusted Publisher bundle")

        bundle = matching_bundles[0]
        publisher = bundle.publisher
        verified: list[tuple[object, Mapping[str, str]]] = []

        for attestation in bundle.attestations:
            try:
                statement = attestation.statement
            except Exception as exc:
                raise ValueError("invalid in-toto statement in PyPI provenance") from exc
            if not isinstance(statement, dict):
                raise ValueError("PyPI attestation statement must be an object")
            if statement.get("_type") != IN_TOTO_STATEMENT_V1:
                continue
            if statement.get("predicateType") != self.spec.predicate_type:
                continue

            try:
                predicate_type, _ = attestation.verify(
                    identity=publisher,
                    dist=distribution,
                    staging=False,
                    offline=self.spec.offline,
                )
            except Exception as exc:
                raise ValueError("PEP 740 attestation cryptographic verification failed") from exc
            if predicate_type != self.spec.predicate_type:
                raise ValueError("verified PyPI attestation returned an unexpected predicate type")

            claims = attestation.certificate_claims
            if not isinstance(claims, dict):
                raise ValueError("certificate claims must be a mapping")
            verified.append((attestation, claims))

        if len(verified) != 1:
            raise ValueError("expected exactly one verified attestation for required predicate")

        attestation, claims = verified[0]
        source_repository_uri = claims.get(SOURCE_REPOSITORY_URI_OID)
        source_repository_digest = claims.get(SOURCE_REPOSITORY_DIGEST_OID)
        build_config_uri = claims.get(BUILD_CONFIG_URI_OID)
        if not source_repository_uri or not source_repository_digest or not build_config_uri:
            raise ValueError("verified certificate is missing required source provenance claims")

        expected_repository_uri = f"https://github.com/{self.spec.expected_repository}"
        if source_repository_uri != expected_repository_uri:
            raise ValueError("verified source repository URI does not match provenance spec")
        source_repository_digest = _commit_sha(
            source_repository_digest,
            "certificate source repository digest",
        )
        if (
            self.spec.expected_source_commit_sha is not None
            and source_repository_digest != self.spec.expected_source_commit_sha
        ):
            raise ValueError("verified source repository digest does not match expected commit")

        expected_build_prefix = (
            f"https://github.com/{self.spec.expected_repository}/.github/workflows/"
            f"{self.spec.expected_workflow}@"
        )
        if not build_config_uri.startswith(expected_build_prefix):
            raise ValueError("verified build config URI does not match expected workflow")

        material = attestation.verification_material
        entries = list(material.transparency_entries)
        if self.spec.require_single_transparency_entry and len(entries) != 1:
            raise ValueError("expected exactly one transparency-log entry")
        if not entries:
            raise ValueError("verified PyPI attestation has no transparency-log entry")

        tlog_bytes = json.dumps(
            entries,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        certificate_bytes = bytes(material.certificate)
        transparency_fingerprint = sha256(tlog_bytes).hexdigest()
        material_fingerprint = sha256(
            certificate_bytes
            + b"\x00"
            + tlog_bytes
            + b"\x00"
            + self.spec.distribution_sha256.encode("ascii")
        ).hexdigest()

        return VerifiedPyPIProvenance(
            distribution_filename=self.spec.distribution_filename,
            distribution_sha256=self.spec.distribution_sha256,
            publisher_identity=self.spec.publisher_identity,
            issuer=GITHUB_OIDC_ISSUER,
            source_repository_uri=source_repository_uri,
            source_repository_digest=source_repository_digest,
            build_config_uri=build_config_uri,
            predicate_type=self.spec.predicate_type,
            verification_material_fingerprint=material_fingerprint,
            transparency_log_fingerprint=transparency_fingerprint,
            provenance_fingerprint=self._provenance_sha256,
            verifier_spec_fingerprint=self.spec.fingerprint,
            verified_attestation_count=1,
        )
