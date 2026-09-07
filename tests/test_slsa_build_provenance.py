from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from growthevo.evolution.promotion_manifest import PromotionSubject, PromotionTransition
from growthevo.evolution.slsa_build_provenance import (
    GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1,
    IN_TOTO_STATEMENT_V1,
    SLSA_PROVENANCE_V1,
    SLSABuilderTrust,
    SLSABuildExpectationSpec,
    SLSABuildProvenanceVerifier,
    canonical_external_parameters,
)


DIGEST = "a" * 64
COMMIT = "b" * 40
REPO = "example/repo"
WORKFLOW = "release.yml"
REF = "refs/tags/v1.0.0"
BUILDER = f"https://github.com/{REPO}/.github/workflows/{WORKFLOW}@{REF}"
PUBLISHER = f"pypi-trusted-publisher:github:{REPO}:.github/workflows/{WORKFLOW}"


def _external() -> dict[str, object]:
    return {
        "workflow": {
            "ref": REF,
            "repository": f"https://github.com/{REPO}",
            "path": f".github/workflows/{WORKFLOW}",
        }
    }


def _trust(*, level: int = 2, builder: str = BUILDER) -> SLSABuilderTrust:
    return SLSABuilderTrust(
        publisher_identity=PUBLISHER,
        builder_id=builder,
        max_build_level=level,
    )


def _spec(**overrides: object) -> SLSABuildExpectationSpec:
    values: dict[str, object] = {
        "distribution_filename": "example_pkg-1.0.0-py3-none-any.whl",
        "distribution_sha256": DIGEST,
        "expected_repository": REPO,
        "expected_workflow": WORKFLOW,
        "expected_source_ref": REF,
        "expected_source_commit_sha": COMMIT,
        "expected_external_parameters_json": canonical_external_parameters(_external()),
        "trusted_builders": (_trust(),),
        "minimum_build_level": 2,
    }
    values.update(overrides)
    return SLSABuildExpectationSpec(**values)


def _subject(commit: str = COMMIT) -> PromotionSubject:
    return PromotionSubject(
        experiment_id="exp",
        candidate_name="candidate",
        candidate_contract_fingerprint="candidate-contract",
        promotion_artifact_fingerprint="promotion-artifact",
        plan_fingerprint="plan",
        commit_sha=commit,
    )


class FakePublisher:
    def __init__(self, repository: str, workflow: str) -> None:
        self.repository = repository
        self.workflow = workflow


class FakeDistribution:
    def __init__(self, *, name: str, digest: str) -> None:
        self.name = name
        self.digest = digest


class FakeMaterial:
    def __init__(self, entries: list[dict[str, object]] | None = None) -> None:
        self.certificate = b"certificate"
        self.transparency_entries = entries if entries is not None else [{"logIndex": 7}]


class FakeAttestation:
    def __init__(
        self,
        *,
        predicate: dict[str, object] | None = None,
        predicate_type: str = SLSA_PROVENANCE_V1,
        verify_error: Exception | None = None,
        entries: list[dict[str, object]] | None = None,
    ) -> None:
        self._predicate = predicate or _predicate()
        self.statement = {
            "_type": IN_TOTO_STATEMENT_V1,
            "subject": [{"name": "example_pkg-1.0.0-py3-none-any.whl", "digest": {"sha256": DIGEST}}],
            "predicateType": predicate_type,
            "predicate": self._predicate,
        }
        self.verification_material = FakeMaterial(entries)
        self._verify_error = verify_error

    def verify(self, *, identity: object, dist: object, staging: bool, offline: bool):
        if self._verify_error:
            raise self._verify_error
        assert isinstance(identity, FakePublisher)
        assert dist.name == "example_pkg-1.0.0-py3-none-any.whl"
        assert dist.digest == DIGEST
        assert staging is False
        assert offline is True
        return self.statement["predicateType"], self._predicate


def _predicate(
    *,
    builder: str = BUILDER,
    build_type: str = GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1,
    external: dict[str, object] | None = None,
    source_uri: str | None = None,
    source_commit: str = COMMIT,
    extra_dependencies: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    deps = [
        {
            "uri": source_uri or f"git+https://github.com/{REPO}@{REF}",
            "digest": {"gitCommit": source_commit},
        }
    ]
    if extra_dependencies:
        deps.extend(extra_dependencies)
    return {
        "buildDefinition": {
            "buildType": build_type,
            "externalParameters": external if external is not None else _external(),
            "internalParameters": {"github": {"event_name": "release"}},
            "resolvedDependencies": deps,
        },
        "runDetails": {
            "builder": {"id": builder},
            "metadata": {"invocationId": "https://github.com/example/repo/actions/runs/1/attempts/1"},
        },
    }


class FakeProvenance:
    current: object | None = None

    @classmethod
    def model_validate_json(cls, raw: bytes):
        assert json.loads(raw.decode("utf-8"))["version"] == 1
        assert cls.current is not None
        return cls.current


def _bundle(attestations: list[FakeAttestation] | None = None, *, repository: str = REPO):
    return SimpleNamespace(
        publisher=FakePublisher(repository, WORKFLOW),
        attestations=attestations or [FakeAttestation()],
    )


def _install(monkeypatch: pytest.MonkeyPatch, bundles: list[object]) -> None:
    FakeProvenance.current = SimpleNamespace(attestation_bundles=bundles)
    module = SimpleNamespace(
        __version__="0.0.30",
        Provenance=FakeProvenance,
        Distribution=FakeDistribution,
        GitHubPublisher=FakePublisher,
    )
    monkeypatch.setitem(__import__("sys").modules, "pypi_attestations", module)


def _raw() -> bytes:
    return b'{"version":1,"attestation_bundles":[]}'


def test_spec_fingerprint_binds_root_buildtype_external_source_and_level() -> None:
    baseline = _spec()
    assert baseline.fingerprint != _spec(minimum_build_level=1).fingerprint
    assert baseline.fingerprint != _spec(trusted_builders=(_trust(level=3),)).fingerprint
    assert baseline.fingerprint != _spec(allowed_build_types=("https://example/build/v1",)).fingerprint
    altered = {**_external(), "extra": "untrusted"}
    assert baseline.fingerprint != _spec(
        expected_external_parameters_json=canonical_external_parameters(altered)
    ).fingerprint
    assert baseline.fingerprint != _spec(expected_source_commit_sha="c" * 40).fingerprint


def test_success_uses_local_root_of_trust_not_predicate_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle()])
    result = SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()
    assert result.builder_id == BUILDER
    assert result.trusted_build_level == 2
    assert result.build_type == GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1
    assert result.source_commit_sha == COMMIT


def test_unknown_builder_or_insufficient_trust_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(builder="https://evil/builder"))])])
    with pytest.raises(ValueError, match="root of trust"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    _install(monkeypatch, [_bundle()])
    with pytest.raises(ValueError, match="required Build level"):
        SLSABuildProvenanceVerifier(
            provenance_json=_raw(),
            spec=_spec(trusted_builders=(_trust(level=1),), minimum_build_level=2),
        ).verify()


def test_build_type_and_external_parameters_are_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(build_type="https://evil/build"))])])
    with pytest.raises(ValueError, match="buildType"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    external = _external()
    external["unrecognized"] = True
    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(external=external))])])
    with pytest.raises(ValueError, match="externalParameters"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_source_dependency_uri_and_commit_are_mandatory(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(source_uri="git+https://github.com/fork/repo@" + REF))])])
    with pytest.raises(ValueError, match="source dependency"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(source_commit="c" * 40))])])
    with pytest.raises(ValueError, match="source dependency"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_ambiguous_duplicate_source_dependency_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = {
        "uri": f"git+https://github.com/{REPO}@{REF}",
        "digest": {"gitCommit": COMMIT},
    }
    _install(monkeypatch, [_bundle([FakeAttestation(predicate=_predicate(extra_dependencies=[duplicate]))])])
    with pytest.raises(ValueError, match="ambiguous"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_crypto_failure_and_predicate_ambiguity_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle([FakeAttestation(verify_error=RuntimeError("bad sig"))])])
    with pytest.raises(ValueError, match="cryptographic"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()

    _install(monkeypatch, [_bundle([FakeAttestation(), FakeAttestation()])])
    with pytest.raises(ValueError, match="exactly one verified"):
        SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()


def test_build_authority_requires_same_promotion_source_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle()])
    verified = SLSABuildProvenanceVerifier(provenance_json=_raw(), spec=_spec()).verify()
    evidence = verified.to_build_authority_evidence(
        subject=_subject(),
        authority_id="build_supply_chain",
        authorized_transitions=(PromotionTransition.ENTER_CANARY,),
        evidence_epoch=4,
        minimum_build_level=2,
    )
    assert evidence.evidence_type == "slsa_build_provenance.v1"
    assert evidence.producer == BUILDER

    with pytest.raises(ValueError, match="source commit"):
        verified.to_build_authority_evidence(
            subject=_subject("c" * 40),
            authority_id="build_supply_chain",
            authorized_transitions=(PromotionTransition.ENTER_CANARY,),
            evidence_epoch=4,
            minimum_build_level=2,
        )

    with pytest.raises(ValueError, match="required SLSA Build level"):
        verified.to_build_authority_evidence(
            subject=_subject(),
            authority_id="build_supply_chain",
            authorized_transitions=(PromotionTransition.ENTER_CANARY,),
            evidence_epoch=4,
            minimum_build_level=3,
        )


def test_provenance_parser_rejects_duplicate_keys_before_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_bundle()])
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SLSABuildProvenanceVerifier(
            provenance_json=b'{"version":1,"version":1}',
            spec=_spec(),
        )


def test_canonical_external_parameter_contract_is_enforced() -> None:
    noncanonical = '{"workflow": {"path": ".github/workflows/release.yml"}}'
    with pytest.raises(ValueError, match="canonical JSON"):
        _spec(expected_external_parameters_json=noncanonical)


def test_trust_root_rejects_duplicate_signer_builder_pairs() -> None:
    with pytest.raises(ValueError, match="repeat"):
        _spec(trusted_builders=(_trust(), _trust(level=3)))
