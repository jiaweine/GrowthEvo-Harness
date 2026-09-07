from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from growthevo.evolution.promotion_manifest import PromotionSubject, PromotionTransition
from growthevo.evolution.pypi_provenance import (
    BUILD_CONFIG_URI_OID,
    GITHUB_OIDC_ISSUER,
    IN_TOTO_STATEMENT_V1,
    PYPI_PUBLISH_PREDICATE_V1,
    SOURCE_REPOSITORY_DIGEST_OID,
    SOURCE_REPOSITORY_URI_OID,
    PyPIPublishProvenanceSpec,
    PyPIPublishProvenanceVerifier,
)


DIGEST = "a" * 64
COMMIT = "b" * 40


def _spec(**overrides: object) -> PyPIPublishProvenanceSpec:
    values: dict[str, object] = {
        "distribution_filename": "example_pkg-1.0.0-py3-none-any.whl",
        "distribution_sha256": DIGEST,
        "expected_repository": "example/repo",
        "expected_workflow": "release.yml",
        "expected_source_commit_sha": COMMIT,
    }
    values.update(overrides)
    return PyPIPublishProvenanceSpec(**values)


def _subject(commit_sha: str = COMMIT) -> PromotionSubject:
    return PromotionSubject(
        experiment_id="exp-1",
        candidate_name="candidate",
        candidate_contract_fingerprint="candidate-contract",
        promotion_artifact_fingerprint="promotion-artifact",
        plan_fingerprint="plan",
        commit_sha=commit_sha,
    )


class FakePublisher:
    def __init__(self, repository: str, workflow: str) -> None:
        self.repository = repository
        self.workflow = workflow


class FakeDistribution:
    def __init__(self, *, name: str, digest: str) -> None:
        self.name = name
        self.digest = digest


class FakeVerificationMaterial:
    def __init__(self, entries: list[dict[str, object]] | None = None) -> None:
        self.certificate = b"certificate-bytes"
        self.transparency_entries = entries or [{"logIndex": 42, "integratedTime": 123}]


class FakeAttestation:
    def __init__(
        self,
        *,
        predicate_type: str = PYPI_PUBLISH_PREDICATE_V1,
        source_digest: str = COMMIT,
        source_uri: str = "https://github.com/example/repo",
        build_config_uri: str = (
            "https://github.com/example/repo/.github/workflows/release.yml@" + COMMIT
        ),
        verify_error: Exception | None = None,
        entries: list[dict[str, object]] | None = None,
    ) -> None:
        self.statement = {
            "_type": IN_TOTO_STATEMENT_V1,
            "subject": [{"name": "example_pkg-1.0.0-py3-none-any.whl", "digest": {"sha256": DIGEST}}],
            "predicateType": predicate_type,
            "predicate": {},
        }
        self.certificate_claims = {
            SOURCE_REPOSITORY_URI_OID: source_uri,
            SOURCE_REPOSITORY_DIGEST_OID: source_digest,
            BUILD_CONFIG_URI_OID: build_config_uri,
        }
        self.verification_material = FakeVerificationMaterial(entries)
        self._verify_error = verify_error
        self.calls: list[tuple[object, object, bool, bool]] = []

    def verify(self, *, identity: object, dist: object, staging: bool, offline: bool):
        self.calls.append((identity, dist, staging, offline))
        if self._verify_error is not None:
            raise self._verify_error
        return self.statement["predicateType"], self.statement["predicate"]


class FakeProvenance:
    current: object | None = None

    @classmethod
    def model_validate_json(cls, raw: bytes):
        assert json.loads(raw.decode("utf-8"))["version"] == 1
        assert cls.current is not None
        return cls.current


def _install_fake_api(monkeypatch: pytest.MonkeyPatch, bundles: list[object]) -> None:
    FakeProvenance.current = SimpleNamespace(attestation_bundles=bundles)
    module = SimpleNamespace(
        __version__="0.0.30",
        Provenance=FakeProvenance,
        Distribution=FakeDistribution,
        GitHubPublisher=FakePublisher,
    )
    monkeypatch.setitem(__import__("sys").modules, "pypi_attestations", module)


def _bundle(
    *,
    repository: str = "example/repo",
    workflow: str = "release.yml",
    attestations: list[FakeAttestation] | None = None,
):
    return SimpleNamespace(
        publisher=FakePublisher(repository, workflow),
        attestations=attestations or [FakeAttestation()],
    )


def _raw() -> bytes:
    return b'{"version":1,"attestation_bundles":[]}'


def test_spec_fingerprint_binds_distribution_publisher_commit_and_mode() -> None:
    baseline = _spec()
    assert baseline.fingerprint != _spec(distribution_sha256="c" * 64).fingerprint
    assert baseline.fingerprint != _spec(expected_repository="other/repo").fingerprint
    assert baseline.fingerprint != _spec(expected_workflow="publish.yml").fingerprint
    assert baseline.fingerprint != _spec(expected_source_commit_sha="d" * 40).fingerprint
    assert baseline.fingerprint != _spec(offline=False).fingerprint


def test_provenance_rejects_duplicate_json_keys_before_sdk_parsing() -> None:
    raw = b'{"version":1,"version":1,"attestation_bundles":[]}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        PyPIPublishProvenanceVerifier(provenance_json=raw, spec=_spec())


def test_provenance_size_limit_fails_closed() -> None:
    spec = _spec(max_provenance_bytes=1024)
    raw = b'{"version":1,"x":"' + b"a" * 2000 + b'"}'
    with pytest.raises(ValueError, match="size limit"):
        PyPIPublishProvenanceVerifier(provenance_json=raw, spec=spec)


def test_success_uses_exact_trusted_publisher_and_source_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    attestation = FakeAttestation()
    _install_fake_api(monkeypatch, [_bundle(attestations=[attestation])])
    result = PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    assert result.publisher_identity == (
        "pypi-trusted-publisher:github:example/repo:.github/workflows/release.yml"
    )
    assert result.issuer == GITHUB_OIDC_ISSUER
    assert result.source_repository_digest == COMMIT
    assert result.distribution_sha256 == DIGEST
    assert result.verified_attestation_count == 1
    assert len(attestation.calls) == 1
    _, dist, staging, offline = attestation.calls[0]
    assert dist.name == "example_pkg-1.0.0-py3-none-any.whl"
    assert dist.digest == DIGEST
    assert staging is False
    assert offline is True


def test_wrong_or_ambiguous_publisher_bundle_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(monkeypatch, [_bundle(repository="attacker/repo")])
    with pytest.raises(ValueError, match="exactly one matching"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    _install_fake_api(monkeypatch, [_bundle(), _bundle()])
    with pytest.raises(ValueError, match="exactly one matching"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_crypto_failure_does_not_emit_verified_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(
        monkeypatch,
        [_bundle(attestations=[FakeAttestation(verify_error=RuntimeError("bad signature"))])],
    )
    with pytest.raises(ValueError, match="cryptographic verification failed"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_wrong_source_commit_and_repository_claims_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(monkeypatch, [_bundle(attestations=[FakeAttestation(source_digest="c" * 40)])])
    with pytest.raises(ValueError, match="expected commit"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    _install_fake_api(
        monkeypatch,
        [_bundle(attestations=[FakeAttestation(source_uri="https://github.com/attacker/repo")])],
    )
    with pytest.raises(ValueError, match="source repository URI"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_wrong_workflow_claim_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(
        monkeypatch,
        [_bundle(attestations=[FakeAttestation(build_config_uri="https://github.com/example/repo/.github/workflows/evil.yml@" + COMMIT)])],
    )
    with pytest.raises(ValueError, match="build config URI"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_required_predicate_is_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    other = FakeAttestation(predicate_type="https://slsa.dev/provenance/v1")
    publish = FakeAttestation()
    _install_fake_api(monkeypatch, [_bundle(attestations=[other, publish])])
    assert PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify().predicate_type == PYPI_PUBLISH_PREDICATE_V1

    _install_fake_api(monkeypatch, [_bundle(attestations=[publish, FakeAttestation()])])
    with pytest.raises(ValueError, match="exactly one verified attestation"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_transparency_entry_cardinality_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    attestation = FakeAttestation(entries=[{"logIndex": 1}, {"logIndex": 2}])
    _install_fake_api(monkeypatch, [_bundle(attestations=[attestation])])
    with pytest.raises(ValueError, match="exactly one transparency"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_sdk_version_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(monkeypatch, [_bundle()])
    module = __import__("sys").modules["pypi_attestations"]
    module.__version__ = "0.0.29"
    with pytest.raises(RuntimeError, match="version"):
        PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_release_authority_evidence_requires_same_source_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(monkeypatch, [_bundle()])
    verified = PyPIPublishProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()
    evidence = verified.to_release_authority_evidence(
        subject=_subject(),
        authority_id="release_supply_chain",
        authorized_transitions=(PromotionTransition.ENTER_CANARY,),
        evidence_epoch=3,
    )
    assert evidence.evidence_type == "pypi_publish_provenance.v1"
    assert evidence.producer == verified.publisher_identity
    assert evidence.subject_fingerprint == _subject().fingerprint
    assert evidence.source_chain_head == verified.transparency_log_fingerprint

    with pytest.raises(ValueError, match="source commit"):
        verified.to_release_authority_evidence(
            subject=_subject("c" * 40),
            authority_id="release_supply_chain",
            authorized_transitions=(PromotionTransition.ENTER_CANARY,),
            evidence_epoch=3,
        )


def test_spec_validation_rejects_path_or_invalid_hash() -> None:
    with pytest.raises(ValueError, match="basename"):
        _spec(distribution_filename="dist/pkg.whl")
    with pytest.raises(ValueError, match="SHA-256"):
        _spec(distribution_sha256="not-a-digest")
    with pytest.raises(ValueError, match="owner/repository"):
        _spec(expected_repository="repo-only")
    with pytest.raises(ValueError, match="workflow filename"):
        _spec(expected_workflow=".github/workflows/release.yml")
