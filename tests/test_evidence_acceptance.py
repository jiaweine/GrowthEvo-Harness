from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "scripts" / "write_evidence_integrity_manifest.py"
VERIFIER = ROOT / "scripts" / "verify_evidence_acceptance.py"
EVIDENCE_COMMIT = "a" * 40
WORKFLOW_RUN_ID = 123456
WORKFLOW_ARTIFACT_ID = 789012


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object, *, compact: bool = False) -> None:
    if compact:
        text = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_integrity(source: Path, integrity: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--root",
            str(source),
            "--output",
            str(integrity),
            "dispatch-provenance.json",
            "full-run.log",
            "result/environment.txt",
            "result/export-manifest.json",
            "result/locked-result.json",
            "result/source-provenance.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _prepare_bundle(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "source"
    result = source / "result"
    result.mkdir(parents=True)
    persisted = tmp_path / "persisted"
    persisted.mkdir()

    locked = {
        "artifact": {"commit_sha": EVIDENCE_COMMIT, "estimate": 0.5},
        "experiment_plan": {"fingerprint": "plan"},
    }
    manifest = {"fingerprint": "export", "source_rows": 123}
    provenance = {"growth_evo_commit_sha": EVIDENCE_COMMIT, "dataset_sha256": "abc"}
    dispatch = {
        "schema_version": "growthevo.research-dispatch.v1",
        "event_name": "workflow_dispatch",
        "commit_sha": EVIDENCE_COMMIT,
        "workflow_sha": EVIDENCE_COMMIT,
        "workflow_sha_matches_commit": True,
        "run_id": str(WORKFLOW_RUN_ID),
        "trusted_branch": "main",
        "commit_is_trusted_ref_ancestor": True,
        "reviewed_pull_request_number": 42,
        "reviewed_pull_request_merge_sha": EVIDENCE_COMMIT,
        "reviewed_pull_request_base_ref": "main",
        "reviewed_ci_run_id": 654321,
        "reviewed_ci_verified": True,
    }

    _write_json(source / "dispatch-provenance.json", dispatch)
    _write_json(result / "locked-result.json", locked)
    _write_json(result / "export-manifest.json", manifest)
    _write_json(result / "source-provenance.json", provenance)
    (result / "environment.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    (source / "full-run.log").write_text("result=/tmp/example\n", encoding="utf-8")

    integrity = source / "evidence-integrity.json"
    _write_integrity(source, integrity)

    _write_json(persisted / "locked-result.json", locked, compact=True)
    _write_json(persisted / "export-manifest.json", manifest, compact=True)
    _write_json(persisted / "source-provenance.json", provenance, compact=True)
    (persisted / "environment.txt").write_bytes((result / "environment.txt").read_bytes())

    metadata = {
        "schema_version": "growthevo.example-evidence-record.v1",
        "evidence_commit_sha": EVIDENCE_COMMIT,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "workflow_artifact_id": WORKFLOW_ARTIFACT_ID,
        "workflow_artifact_digest": "sha256:" + "b" * 64,
        "source_artifact_file_sha256": {
            "dispatch-provenance.json": _sha256(source / "dispatch-provenance.json"),
            "environment.txt": _sha256(result / "environment.txt"),
            "export-manifest.json": _sha256(result / "export-manifest.json"),
            "full-run.log": _sha256(source / "full-run.log"),
            "locked-result.json": _sha256(result / "locked-result.json"),
            "source-provenance.json": _sha256(result / "source-provenance.json"),
        },
        "persisted_copy_format": {
            "dispatch-provenance.json": (
                "not persisted; source dispatch identity retained only in the workflow artifact"
            ),
            "environment.txt": "byte-identical source artifact copy",
            "export-manifest.json": (
                "content-preserving compact JSON; compare parsed content/fingerprint to the source artifact"
            ),
            "full-run.log": "not persisted; source transcript retained only in the workflow artifact",
            "locked-result.json": (
                "content-preserving compact JSON; compare parsed content/fingerprints to the source artifact"
            ),
            "source-provenance.json": (
                "content-preserving compact JSON; source provenance fields are unchanged"
            ),
        },
    }
    metadata_path = persisted / "evidence-metadata.json"
    _write_json(metadata_path, metadata)
    return source, integrity, persisted, metadata_path


def _reseal_dispatch(source: Path, integrity: Path, metadata: Path) -> None:
    _write_integrity(source, integrity)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["source_artifact_file_sha256"]["dispatch-provenance.json"] = _sha256(
        source / "dispatch-provenance.json"
    )
    _write_json(metadata, payload)


def _verify(
    source: Path,
    integrity: Path,
    persisted: Path,
    metadata: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--source-root",
            str(source),
            "--integrity-manifest",
            str(integrity),
            "--persisted-root",
            str(persisted),
            "--metadata",
            str(metadata),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_acceptance_verifier_links_verified_source_bundle_to_persisted_copies(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "growthevo.evidence-acceptance-verification.v1"
    assert result["evidence_commit_sha"] == EVIDENCE_COMMIT
    assert result["workflow_run_id"] == WORKFLOW_RUN_ID
    assert result["workflow_artifact_id"] == WORKFLOW_ARTIFACT_ID
    assert result["reviewed_pull_request_number"] == 42
    assert result["reviewed_ci_run_id"] == 654321
    assert result["verified_source_file_count"] == 6
    assert result["accepted_file_count"] == 6
    modes = {row["logical_name"]: row["copy_mode"] for row in result["verified_files"]}
    assert modes == {
        "dispatch-provenance.json": "source-only",
        "environment.txt": "byte-identical",
        "export-manifest.json": "json-semantic-identical",
        "full-run.log": "source-only",
        "locked-result.json": "json-semantic-identical",
        "source-provenance.json": "json-semantic-identical",
    }


def test_acceptance_verifier_rejects_tampered_source_bundle(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    (source / "full-run.log").write_text("tampered\n", encoding="utf-8")

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "evidence integrity verification failed" in completed.stderr


def test_acceptance_verifier_rejects_metadata_source_sha_mismatch(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["source_artifact_file_sha256"]["environment.txt"] = "sha256:" + "0" * 64
    _write_json(metadata, payload)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "metadata source SHA256 does not match verified integrity manifest" in completed.stderr


def test_acceptance_verifier_rejects_changed_semantic_json_copy(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    changed = json.loads((persisted / "locked-result.json").read_text(encoding="utf-8"))
    changed["artifact"]["estimate"] = 0.6
    _write_json(persisted / "locked-result.json", changed, compact=True)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "persisted JSON content differs from source artifact" in completed.stderr


def test_acceptance_verifier_rejects_file_declared_not_persisted_when_present(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    (persisted / "full-run.log").write_text("unexpected persisted transcript\n", encoding="utf-8")

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "metadata declares not persisted but a persisted file exists" in completed.stderr


def test_acceptance_verifier_rejects_unknown_copy_mode(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["persisted_copy_format"]["environment.txt"] = "approximately copied"
    _write_json(metadata, payload)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "unsupported persisted copy format" in completed.stderr


def test_acceptance_verifier_rejects_inconsistent_copy_contract_keys(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    del payload["persisted_copy_format"]["full-run.log"]
    _write_json(metadata, payload)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "must name the same files" in completed.stderr


def test_acceptance_verifier_rejects_workflow_run_id_mismatch(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["workflow_run_id"] = WORKFLOW_RUN_ID + 1
    _write_json(metadata, payload)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "workflow_run_id does not match source dispatch provenance run_id" in completed.stderr


def test_acceptance_verifier_rejects_dispatch_commit_mismatch_even_when_resealed(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    dispatch_path = source / "dispatch-provenance.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    dispatch["commit_sha"] = "c" * 40
    _write_json(dispatch_path, dispatch)
    _reseal_dispatch(source, integrity, metadata)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "commit_sha does not match metadata evidence_commit_sha" in completed.stderr


def test_acceptance_verifier_rejects_non_dispatch_source_even_when_resealed(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    dispatch_path = source / "dispatch-provenance.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    dispatch["event_name"] = "push"
    _write_json(dispatch_path, dispatch)
    _reseal_dispatch(source, integrity, metadata)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "event_name=workflow_dispatch" in completed.stderr


def test_acceptance_verifier_rejects_unreviewed_dispatch_even_when_resealed(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    dispatch_path = source / "dispatch-provenance.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    dispatch["reviewed_ci_verified"] = False
    _write_json(dispatch_path, dispatch)
    _reseal_dispatch(source, integrity, metadata)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "reviewed_ci_verified=true" in completed.stderr


def test_acceptance_verifier_requires_positive_platform_ids(tmp_path: Path) -> None:
    source, integrity, persisted, metadata = _prepare_bundle(tmp_path)
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["workflow_artifact_id"] = 0
    _write_json(metadata, payload)

    completed = _verify(source, integrity, persisted, metadata)

    assert completed.returncode != 0
    assert "workflow_artifact_id must be a positive integer" in completed.stderr
