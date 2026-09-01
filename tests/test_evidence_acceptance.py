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


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object, *, compact: bool = False) -> None:
    if compact:
        text = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


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

    _write_json(result / "locked-result.json", locked)
    _write_json(result / "export-manifest.json", manifest)
    _write_json(result / "source-provenance.json", provenance)
    (result / "environment.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    (source / "full-run.log").write_text("result=/tmp/example\n", encoding="utf-8")

    integrity = source / "evidence-integrity.json"
    subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--root",
            str(source),
            "--output",
            str(integrity),
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

    _write_json(persisted / "locked-result.json", locked, compact=True)
    _write_json(persisted / "export-manifest.json", manifest, compact=True)
    _write_json(persisted / "source-provenance.json", provenance, compact=True)
    (persisted / "environment.txt").write_bytes((result / "environment.txt").read_bytes())

    metadata = {
        "schema_version": "growthevo.example-evidence-record.v1",
        "evidence_commit_sha": EVIDENCE_COMMIT,
        "workflow_artifact_digest": "sha256:" + "b" * 64,
        "source_artifact_file_sha256": {
            "environment.txt": _sha256(result / "environment.txt"),
            "export-manifest.json": _sha256(result / "export-manifest.json"),
            "full-run.log": _sha256(source / "full-run.log"),
            "locked-result.json": _sha256(result / "locked-result.json"),
            "source-provenance.json": _sha256(result / "source-provenance.json"),
        },
        "persisted_copy_format": {
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
    assert result["verified_source_file_count"] == 5
    assert result["accepted_file_count"] == 5
    modes = {row["logical_name"]: row["copy_mode"] for row in result["verified_files"]}
    assert modes == {
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
