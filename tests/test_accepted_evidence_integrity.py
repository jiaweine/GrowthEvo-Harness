from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_accepted_evidence_integrity.py"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    evidence = repo / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "a.json").write_text('{"value":"accepted-a"}\n', encoding="utf-8")
    (evidence / "b.json").write_text('{"value":"accepted-b"}\n', encoding="utf-8")

    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "GrowthEvo CI")
    _git(repo, "add", "evidence/a.json", "evidence/b.json")
    _git(repo, "commit", "-m", "accepted evidence")

    files = []
    for relative in ("evidence/a.json", "evidence/b.json"):
        path = repo / relative
        files.append(
            {
                "path": relative,
                "git_blob_sha": _git(repo, "rev-parse", f"HEAD:{relative}"),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "growthevo.accepted-evidence-integrity.v1",
        "git_object_format": _git(repo, "rev-parse", "--show-object-format"),
        "evidence_sets": [
            {
                "name": "accepted/example",
                "files": files,
            }
        ],
    }
    manifest_path = repo / "accepted-evidence-integrity.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return repo, manifest_path


def _verify(repo: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--repo-root",
            str(repo),
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_accepted_evidence_verifier_accepts_exact_committed_bytes(tmp_path: Path) -> None:
    repo, manifest = _init_repo(tmp_path)

    completed = _verify(repo, manifest)

    assert completed.returncode == 0, completed.stderr
    verified = json.loads(completed.stdout)
    assert verified["schema_version"] == "growthevo.accepted-evidence-integrity.v1"
    assert verified["file_count"] == 2
    assert [entry["path"] for entry in verified["verified_files"]] == [
        "evidence/a.json",
        "evidence/b.json",
    ]


def test_accepted_evidence_verifier_rejects_uncommitted_tamper(tmp_path: Path) -> None:
    repo, manifest = _init_repo(tmp_path)
    original = repo / "evidence" / "a.json"
    tampered = original.read_text(encoding="utf-8").replace("accepted-a", "rejected-a")
    assert len(tampered.encode()) == original.stat().st_size
    original.write_text(tampered, encoding="utf-8")

    completed = _verify(repo, manifest)

    assert completed.returncode != 0
    assert "accepted evidence worktree blob mismatch" in completed.stderr


def test_accepted_evidence_verifier_rejects_committed_drift_without_reseal(tmp_path: Path) -> None:
    repo, manifest = _init_repo(tmp_path)
    evidence = repo / "evidence" / "a.json"
    drifted = evidence.read_text(encoding="utf-8").replace("accepted-a", "rejected-a")
    assert len(drifted.encode()) == evidence.stat().st_size
    evidence.write_text(drifted, encoding="utf-8")
    _git(repo, "add", "evidence/a.json")
    _git(repo, "commit", "-m", "drift accepted evidence")

    completed = _verify(repo, manifest)

    assert completed.returncode != 0
    assert "accepted evidence committed blob mismatch" in completed.stderr


def test_accepted_evidence_verifier_rejects_duplicate_evidence_set_names(tmp_path: Path) -> None:
    repo, manifest = _init_repo(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    files = payload["evidence_sets"][0]["files"]
    payload["evidence_sets"] = [
        {"name": "accepted/example", "files": [files[0]]},
        {"name": "accepted/example", "files": [files[1]]},
    ]
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = _verify(repo, manifest)

    assert completed.returncode != 0
    assert "evidence set names must be unique" in completed.stderr
