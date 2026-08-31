from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "scripts" / "write_evidence_integrity_manifest.py"
VERIFIER = ROOT / "scripts" / "verify_evidence_integrity_manifest.py"


def _write_bundle(tmp_path: Path) -> Path:
    (tmp_path / "result").mkdir()
    (tmp_path / "dispatch-provenance.json").write_text('{"commit":"abc"}\n', encoding="utf-8")
    (tmp_path / "result" / "locked-result.json").write_text('{"estimate":0.5}\n', encoding="utf-8")
    manifest = tmp_path / "evidence-integrity.json"
    subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--root",
            str(tmp_path),
            "--output",
            str(manifest),
            "dispatch-provenance.json",
            "result/locked-result.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return manifest


def _verify(tmp_path: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--root",
            str(tmp_path),
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_verifier_accepts_valid_manifest_and_ignores_unlisted_diagnostics(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    (tmp_path / "full-run.log").write_text("diagnostic only\n", encoding="utf-8")

    completed = _verify(tmp_path, manifest)

    assert completed.returncode == 0, completed.stderr
    verified = json.loads(completed.stdout)
    assert verified["schema_version"] == "growthevo.evidence-integrity.v1"
    assert [entry["path"] for entry in verified["files"]] == [
        "dispatch-provenance.json",
        "result/locked-result.json",
    ]


def test_verifier_rejects_tampered_evidence_bytes(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    (tmp_path / "result" / "locked-result.json").write_text('{"estimate":0.6}\n', encoding="utf-8")

    completed = _verify(tmp_path, manifest)

    assert completed.returncode != 0
    assert "sha256 mismatch" in completed.stderr


def test_verifier_rejects_missing_evidence_file(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    (tmp_path / "dispatch-provenance.json").unlink()

    completed = _verify(tmp_path, manifest)

    assert completed.returncode != 0
    assert "missing evidence file" in completed.stderr


@pytest.mark.parametrize(
    (mutation, expected_message),
    [
        (lambda payload: payload.__setitem__("schema_version", "growthevo.evidence-integrity.v0"), "unsupported integrity manifest schema"),
        (lambda payload: payload.__setitem__("unexpected", True), "keys mismatch"),
        (lambda payload: payload["files"].reverse(), "canonically sorted"),
        (lambda payload: payload.__setitem__("file_count", 99), "file_count mismatch"),
    ],
)
def test_verifier_rejects_malformed_manifest(
    tmp_path: Path, mutation, expected_message: str
) -> None:
    manifest = _write_bundle(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    mutation(payload)
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = _verify(tmp_path, manifest)

    assert completed.returncode != 0
    assert expected_message in completed.stderr
