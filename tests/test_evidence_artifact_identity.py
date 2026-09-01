from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "verify_evidence_artifact_identity",
    SCRIPTS / "verify_evidence_artifact_identity.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REPOSITORY = "example/GrowthEvo-Harness"
COMMIT = "a" * 40
RUN_ID = 123456789
ARTIFACT_ID = 987654321
DIGEST = "sha256:" + "b" * 64
WORKFLOW_PATH = ".github/workflows/full-obd-pr-validation.yml"
ARTIFACT_NAME = "obd-full-preregistered-evidence"
REPOSITORY_ID = 424242


def _write_metadata(path: Path, **overrides: object) -> None:
    payload: dict[str, object] = {
        "schema_version": "growthevo.example-evidence-record.v1",
        "evidence_commit_sha": COMMIT,
        "workflow_run_id": RUN_ID,
        "workflow_artifact_id": ARTIFACT_ID,
        "workflow_artifact_digest": DIGEST,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    run = {
        "id": RUN_ID,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_sha": COMMIT,
        "path": WORKFLOW_PATH,
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
    }
    artifact = {
        "id": ARTIFACT_ID,
        "name": ARTIFACT_NAME,
        "expired": False,
        "digest": DIGEST,
        "workflow_run": {
            "id": RUN_ID,
            "repository_id": REPOSITORY_ID,
            "head_repository_id": REPOSITORY_ID,
            "head_sha": COMMIT,
        },
    }
    return run, artifact


def _install_api(monkeypatch: pytest.MonkeyPatch, run: dict[str, Any], artifact: dict[str, Any]) -> None:
    expected = {
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}": run,
        f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}": artifact,
    }

    def fake_github_json(path: str) -> object:
        if path not in expected:
            raise AssertionError(f"unexpected GitHub API path: {path}")
        return expected[path]

    monkeypatch.setattr(MODULE, "_github_json", fake_github_json)


def _verify(metadata: Path) -> dict[str, object]:
    return MODULE.verify_artifact_identity(
        metadata_path=metadata,
        repository=REPOSITORY,
        expected_workflow_path=WORKFLOW_PATH,
        expected_artifact_name=ARTIFACT_NAME,
    )


def test_platform_verifier_binds_successful_run_and_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    _install_api(monkeypatch, run, artifact)

    result = _verify(metadata)

    assert result == {
        "schema_version": "growthevo.evidence-artifact-identity-verification.v1",
        "repository": REPOSITORY,
        "evidence_commit_sha": COMMIT,
        "workflow_run_id": RUN_ID,
        "workflow_path": WORKFLOW_PATH,
        "workflow_event": "workflow_dispatch",
        "workflow_status": "completed",
        "workflow_conclusion": "success",
        "workflow_artifact_id": ARTIFACT_ID,
        "workflow_artifact_name": ARTIFACT_NAME,
        "workflow_artifact_digest": DIGEST,
        "workflow_artifact_expired": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event", "push", "event=workflow_dispatch"),
        ("conclusion", "failure", "not a completed success"),
        ("head_sha", "c" * 40, "head_sha does not match"),
        ("path", ".github/workflows/ci.yml", "path does not match"),
    ],
)
def test_platform_verifier_rejects_wrong_workflow_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    run[field] = value
    _install_api(monkeypatch, run, artifact)

    with pytest.raises(RuntimeError, match=message):
        _verify(metadata)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "wrong-evidence", "artifact name does not match"),
        ("expired", True, "artifact is expired"),
        ("digest", "sha256:" + "c" * 64, "artifact digest does not match"),
    ],
)
def test_platform_verifier_rejects_wrong_artifact_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    artifact[field] = value
    _install_api(monkeypatch, run, artifact)

    with pytest.raises(RuntimeError, match=message):
        _verify(metadata)


def test_platform_verifier_rejects_artifact_from_other_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    artifact["workflow_run"]["id"] = RUN_ID + 1
    _install_api(monkeypatch, run, artifact)

    with pytest.raises(RuntimeError, match="does not belong to metadata workflow_run_id"):
        _verify(metadata)


def test_platform_verifier_rejects_artifact_from_other_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    artifact["workflow_run"]["head_sha"] = "c" * 40
    _install_api(monkeypatch, run, artifact)

    with pytest.raises(RuntimeError, match="workflow_run head_sha does not match evidence commit"):
        _verify(metadata)


def test_platform_verifier_rejects_artifact_repository_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata)
    run, artifact = _payloads()
    artifact["workflow_run"]["repository_id"] = REPOSITORY_ID + 1
    _install_api(monkeypatch, run, artifact)

    with pytest.raises(RuntimeError, match="repository identity does not match"):
        _verify(metadata)


def test_platform_verifier_rejects_malformed_metadata_before_api_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "evidence-metadata.json"
    _write_metadata(metadata, workflow_artifact_digest="sha256:ABC")

    def no_api(_: str) -> object:
        raise AssertionError("GitHub API must not be called for malformed metadata")

    monkeypatch.setattr(MODULE, "_github_json", no_api)
    with pytest.raises(ValueError, match="workflow_artifact_digest"):
        _verify(metadata)
