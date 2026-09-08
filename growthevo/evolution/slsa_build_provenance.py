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
from .pypi_provenance import (
    GITHUB_OIDC_ISSUER,
    PYPI_ATTESTATIONS_VERSION,
)


SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1 = "https://actions.github.io/buildtypes/workflow/v1"
IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"


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


def _parse_object_json(value: str, name: str) -> Mapping[str, object]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty canonical JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must encode a JSON object")
    canonical = _canonical_json(parsed).decode("utf-8")
    if value != canonical:
        raise ValueError(f"{name} must use canonical JSON serialization")
    return parsed


def canonical_external_parameters(parameters: Mapping[str, object]) -> str:
    if not isinstance(parameters, Mapping):
        raise TypeError("parameters must be a mapping")
    return _canonical_json(dict(parameters)).decode("utf-8")


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
class SLSABuilderTrust:
    """Local root-of-trust entry for one authenticated signer/builder pair.

    SLSA Build level is a verifier-side trust decision. It is never inferred from a
    predicate field or from a builder's own claim.
    """

    publisher_identity: str
    builder_id: str
    max_build_level: int

    def __post_init__(self) -> None:
        _nonempty(self.publisher_identity, "publisher_identity")
        _nonempty(self.builder_id, "builder_id")
        if (
            isinstance(self.max_build_level, bool)
            or not isinstance(self.max_build_level, int)
            or not 1 <= self.max_build_level <= 3
        ):
            raise ValueError("max_build_level must be an integer from 1 through 3")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.slsa-builder-trust.v1",
                **asdict(self),
            }
        )


@dataclass(frozen=True, slots=True)
class SLSABuildExpectationSpec:
    distribution_filename: str
    distribution_sha256: str
    expected_repository: str
    expected_workflow: str
    expected_source_ref: str
    expected_source_commit_sha: str
    expected_external_parameters_json: str
    trusted_builders: tuple[SLSABuilderTrust, ...]
    minimum_build_level: int = 2
    allowed_build_types: tuple[str, ...] = (GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1,)
    predicate_type: str = SLSA_PROVENANCE_V1
    pypi_attestations_version: str = PYPI_ATTESTATIONS_VERSION
    offline: bool = True
    max_provenance_bytes: int = 1_000_000
    require_unique_source_dependency: bool = True
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
        _nonempty(self.expected_source_ref, "expected_source_ref")
        if not self.expected_source_ref.startswith("refs/"):
            raise ValueError("expected_source_ref must be a full refs/... value")
        object.__setattr__(
            self,
            "expected_source_commit_sha",
            _commit_sha(self.expected_source_commit_sha, "expected_source_commit_sha"),
        )
        _parse_object_json(
            self.expected_external_parameters_json,
            "expected_external_parameters_json",
        )
        if not self.trusted_builders:
            raise ValueError("trusted_builders cannot be empty")
        pairs = [(item.publisher_identity, item.builder_id) for item in self.trusted_builders]
        if len(set(pairs)) != len(pairs):
            raise ValueError("trusted_builders cannot repeat a publisher/builder pair")
        if (
            isinstance(self.minimum_build_level, bool)
            or not isinstance(self.minimum_build_level, int)
            or not 1 <= self.minimum_build_level <= 3
        ):
            raise ValueError("minimum_build_level must be an integer from 1 through 3")
        if not self.allowed_build_types:
            raise ValueError("allowed_build_types cannot be empty")
        if len(set(self.allowed_build_types)) != len(self.allowed_build_types):
            raise ValueError("allowed_build_types must be unique")
        for value in self.allowed_build_types:
            _nonempty(value, "allowed_build_types")
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
    def expected_source_repository(self) -> str:
        return f"https://github.com/{self.expected_repository}"

    @property
    def expected_source_dependency_uri(self) -> str:
        return f"git+{self.expected_source_repository}@{self.expected_source_ref}"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.slsa-build-expectation.v1",
                "distribution_filename": self.distribution_filename,
                "distribution_sha256": self.distribution_sha256,
                "expected_repository": self.expected_repository,
                "expected_workflow": self.expected_workflow,
                "expected_source_ref": self.expected_source_ref,
                "expected_source_commit_sha": self.expected_source_commit_sha,
                "expected_external_parameters_json": self.expected_external_parameters_json,
                "trusted_builders": [item.fingerprint for item in self.trusted_builders],
                "minimum_build_level": self.minimum_build_level,
                "allowed_build_types": list(self.allowed_build_types),
                "predicate_type": self.predicate_type,
                "pypi_attestations_version": self.pypi_attestations_version,
                "offline": self.offline,
                "max_provenance_bytes": self.max_provenance_bytes,
                "require_unique_source_dependency": self.require_unique_source_dependency,
                "require_single_transparency_entry": self.require_single_transparency_entry,
                "unknown_external_parameters": "reject_by_exact_equality",
                "build_level_source": "local_root_of_trust",
            }
        )

    def trust_for(self, *, publisher_identity: str, builder_id: str) -> SLSABuilderTrust:
        for trust in self.trusted_builders:
            if (
                trust.publisher_identity == publisher_identity
                and trust.builder_id == builder_id
            ):
                return trust
        raise ValueError("authenticated signer/builder pair is not in the SLSA root of trust")


@dataclass(frozen=True, slots=True)
class VerifiedSLSABuildProvenance:
    distribution_filename: str
    distribution_sha256: str
    publisher_identity: str
    issuer: str
    builder_id: str
    trusted_build_level: int
    build_type: str
    external_parameters_fingerprint: str
    resolved_dependencies_fingerprint: str
    source_dependency_uri: str
    source_commit_sha: str
    predicate_fingerprint: str
    verification_material_fingerprint: str
    transparency_log_fingerprint: str
    provenance_fingerprint: str
    expectation_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "distribution_filename",
            "publisher_identity",
            "issuer",
            "builder_id",
            "build_type",
            "external_parameters_fingerprint",
            "resolved_dependencies_fingerprint",
            "source_dependency_uri",
            "predicate_fingerprint",
            "verification_material_fingerprint",
            "transparency_log_fingerprint",
            "provenance_fingerprint",
            "expectation_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        object.__setattr__(
            self,
            "distribution_sha256",
            _sha256_hex(self.distribution_sha256, "distribution_sha256"),
        )
        object.__setattr__(
            self,
            "source_commit_sha",
            _commit_sha(self.source_commit_sha, "source_commit_sha"),
        )
        if (
            isinstance(self.trusted_build_level, bool)
            or not isinstance(self.trusted_build_level, int)
            or not 1 <= self.trusted_build_level <= 3
        ):
            raise ValueError("trusted_build_level must be an integer from 1 through 3")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.verified-slsa-build-provenance.v1",
                **asdict(self),
            },
            digest_size=32,
        )

    def to_build_authority_evidence(
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
            raise ValueError("SLSA source commit does not match promotion subject")
        if (
            isinstance(minimum_build_level, bool)
            or not isinstance(minimum_build_level, int)
            or not 1 <= minimum_build_level <= 3
        ):
            raise ValueError("minimum_build_level must be an integer from 1 through 3")
        if self.trusted_build_level < minimum_build_level:
            raise ValueError("verified builder is not trusted at the required SLSA Build level")
        transitions = tuple(authorized_transitions)
        if not transitions:
            raise ValueError("authorized_transitions cannot be empty")
        return AuthorityEvidence(
            authority_id=authority_id,
            evidence_type="slsa_build_provenance.v1",
            producer=self.builder_id,
            subject_fingerprint=subject.fingerprint,
            protocol_fingerprint=self.expectation_fingerprint,
            artifact_fingerprint=self.fingerprint,
            verdict=AuthorityVerdict.SATISFIED,
            authorized_transitions=transitions,
            evidence_epoch=evidence_epoch,
            source_chain_head=self.transparency_log_fingerprint,
            details_fingerprint=self.fingerprint,
        )


class SLSABuildProvenanceVerifier:
    """Verify SLSA v1 provenance transported through PyPI PEP 740.

    Cryptographic verification and Trusted Publisher authentication are delegated to
    the pinned pypi-attestations/Sigstore stack. GrowthEvo then performs the SLSA
    consumer-side expectation checks that the SLSA specification requires: artifact,
    signer/builder root, buildType, externalParameters and source dependency.
    """

    def __init__(self, *, provenance_json: bytes, spec: SLSABuildExpectationSpec) -> None:
        if len(provenance_json) > spec.max_provenance_bytes:
            raise ValueError("provenance_json exceeds preregistered size limit")
        _reject_duplicate_keys(provenance_json)
        self.spec = spec
        self._raw = provenance_json
        self._provenance_sha256 = sha256(provenance_json).hexdigest()

    def verify(self) -> VerifiedSLSABuildProvenance:
        try:
            import pypi_attestations as pypi_api
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "SLSA PyPI provenance verification requires the optional attestation-pypi extra"
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
        candidates: list[tuple[object, Mapping[str, object]]] = []
        for attestation in bundle.attestations:
            statement = attestation.statement
            if not isinstance(statement, dict):
                raise ValueError("SLSA attestation statement must be an object")
            if statement.get("_type") != IN_TOTO_STATEMENT_V1:
                continue
            if statement.get("predicateType") != self.spec.predicate_type:
                continue
            try:
                predicate_type, predicate = attestation.verify(
                    identity=publisher,
                    dist=distribution,
                    staging=False,
                    offline=self.spec.offline,
                )
            except Exception as exc:
                raise ValueError("SLSA attestation cryptographic verification failed") from exc
            if predicate_type != self.spec.predicate_type or not isinstance(predicate, dict):
                raise ValueError("verified SLSA attestation returned an invalid predicate")
            candidates.append((attestation, predicate))

        if len(candidates) != 1:
            raise ValueError("expected exactly one verified SLSA provenance attestation")

        attestation, predicate = candidates[0]
        build_definition = predicate.get("buildDefinition")
        run_details = predicate.get("runDetails")
        if not isinstance(build_definition, dict) or not isinstance(run_details, dict):
            raise ValueError("SLSA predicate is missing buildDefinition or runDetails")

        build_type = build_definition.get("buildType")
        if build_type not in self.spec.allowed_build_types:
            raise ValueError("SLSA buildType is not approved")

        external_parameters = build_definition.get("externalParameters")
        if not isinstance(external_parameters, dict):
            raise ValueError("SLSA externalParameters must be an object")
        expected_external = _parse_object_json(
            self.spec.expected_external_parameters_json,
            "expected_external_parameters_json",
        )
        if external_parameters != expected_external:
            raise ValueError("SLSA externalParameters do not exactly match expectations")

        builder = run_details.get("builder")
        if not isinstance(builder, dict):
            raise ValueError("SLSA runDetails.builder must be an object")
        builder_id = builder.get("id")
        if not isinstance(builder_id, str) or not builder_id:
            raise ValueError("SLSA builder.id must be a non-empty string")
        trust = self.spec.trust_for(
            publisher_identity=self.spec.publisher_identity,
            builder_id=builder_id,
        )
        if trust.max_build_level < self.spec.minimum_build_level:
            raise ValueError("SLSA builder root is below the required Build level")

        dependencies = build_definition.get("resolvedDependencies")
        if not isinstance(dependencies, list):
            raise ValueError("SLSA resolvedDependencies must be an array")
        source_matches: list[Mapping[str, object]] = []
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            if dependency.get("uri") != self.spec.expected_source_dependency_uri:
                continue
            digest = dependency.get("digest")
            if not isinstance(digest, dict):
                continue
            commit = digest.get("gitCommit")
            if isinstance(commit, str) and _commit_sha(commit, "resolved gitCommit") == self.spec.expected_source_commit_sha:
                source_matches.append(dependency)
        if not source_matches:
            raise ValueError("SLSA provenance lacks the expected source dependency/commit")
        if self.spec.require_unique_source_dependency and len(source_matches) != 1:
            raise ValueError("SLSA provenance contains ambiguous matching source dependencies")

        material = attestation.verification_material
        entries = list(material.transparency_entries)
        if self.spec.require_single_transparency_entry and len(entries) != 1:
            raise ValueError("expected exactly one transparency-log entry")
        if not entries:
            raise ValueError("verified SLSA attestation has no transparency-log entry")

        tlog_bytes = _canonical_json(entries)
        certificate_bytes = bytes(material.certificate)
        predicate_fingerprint = sha256(_canonical_json(predicate)).hexdigest()
        dependencies_fingerprint = sha256(_canonical_json(dependencies)).hexdigest()
        external_fingerprint = sha256(_canonical_json(external_parameters)).hexdigest()
        transparency_fingerprint = sha256(tlog_bytes).hexdigest()
        material_fingerprint = sha256(
            certificate_bytes
            + b"\x00"
            + tlog_bytes
            + b"\x00"
            + predicate_fingerprint.encode("ascii")
        ).hexdigest()

        return VerifiedSLSABuildProvenance(
            distribution_filename=self.spec.distribution_filename,
            distribution_sha256=self.spec.distribution_sha256,
            publisher_identity=self.spec.publisher_identity,
            issuer=GITHUB_OIDC_ISSUER,
            builder_id=builder_id,
            trusted_build_level=trust.max_build_level,
            build_type=build_type,
            external_parameters_fingerprint=external_fingerprint,
            resolved_dependencies_fingerprint=dependencies_fingerprint,
            source_dependency_uri=self.spec.expected_source_dependency_uri,
            source_commit_sha=self.spec.expected_source_commit_sha,
            predicate_fingerprint=predicate_fingerprint,
            verification_material_fingerprint=material_fingerprint,
            transparency_log_fingerprint=transparency_fingerprint,
            provenance_fingerprint=self._provenance_sha256,
            expectation_fingerprint=self.spec.fingerprint,
        )
