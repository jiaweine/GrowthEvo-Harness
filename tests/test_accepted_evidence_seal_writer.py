from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "scripts" / "append_accepted_evidence_seal.py"
VERIFIER = ROOT / "scripts" / "verify_accepted_evidence_integrity.py"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _init_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    repo = tmp_path / "repo"
    evidence = repo / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "old-a.json").write_text('{"value":"old-a"}\n', encoding="utf-8")
    (evidence / "old-b.json").write_text('{"value":"old-b"}\n', encoding="utf-8")

    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "GrowthEvo CI")
    _git(repo, "add", "evidence/old-a.json", "evidence/old-b.json")
    _git(repo, "commit", "-m", "commit accepted evidence")

    old_files = []
    for relative in ("evidence/old-a.json", "evidence/old-b.json"):
        path = repo / relative
        old_files.append(
            {
                "path": relative,
                "git_blob_sha": _git(repo, "rev-parse", f"HEAD:{relative}"),
                "size_bytes": path.stat().st_size,
            }
        )
    old_set: dict[str, object] = {
        "name": "accepted/old",
        "files": old_files,
    }
    manifest = {
        "schema_version": "growthevo.accepted-evidence-integrity.v1",
        "git_object_format": _git(repo, "rev-parse", "--show-object-format"),
        "evidence_sets": [old_set],
    }
    manifest_path = repo / "accepted-evidence-integrity.json"
    _write_json(manifest_path, manifest)
    _git(repo, "add", "accepted-evidence-integrity.json")
    _git(repo, "commit", "-m", "seal accepted evidence")
    return repo, manifest_path, old_set


def _writer(
    repo: Path,
    manifest: Path,
    *,
    name: str = "accepted/new",
    files: tuple[str, ...] = ("evidence/new.json",),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--repo-root",
            str(repo),
            "--manifest",
            str(manifest),
            "--name",
            name,
            *files,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _verifier(repo: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
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


def test_writer_appends_only_new_indexed_set_and_final_verifier_accepts_commit(tmp_path: Path) -> None:
    repo, manifest, old_set = _init_repo(tmp_path)
    (repo / "evidence" / "z.json").write_text('{"value":"z"}\n', encoding="utf-8")
    (repo / "evidence" / "a.json").write_text('{"value":"a"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/z.json", "evidence/a.json")

    completed = _writer(
        repo,
        manifest,
        name="accepted/future",
        files=("evidence/z.json", "evidence/a.json"),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert [row["name"] for row in payload["evidence_sets"]] == [
        "accepted/future",
        "accepted/old",
    ]
    assert payload["evidence_sets"][1] == old_set
    future = payload["evidence_sets"][0]
    assert [row["path"] for row in future["files"]] == [
        "evidence/a.json",
        "evidence/z.json",
    ]
    for row in future["files"]:
        relative = row["path"]
        assert row["git_blob_sha"] == _git(repo, "rev-parse", f":{relative}")
        assert row["size_bytes"] == (repo / relative).stat().st_size

    _git(repo, "add", "accepted-evidence-integrity.json")
    _git(repo, "commit", "-m", "append accepted evidence seal")
    verified = _verifier(repo, manifest)
    assert verified.returncode == 0, verified.stderr
    result = json.loads(verified.stdout)
    assert result["file_count"] == 4


def test_writer_rejects_existing_sealed_evidence_drift_before_append(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    old = repo / "evidence" / "old-a.json"
    old.write_text('{"value":"drift"}\n', encoding="utf-8")
    (repo / "evidence" / "new.json").write_text('{"value":"new"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/new.json")

    completed = _writer(repo, manifest)

    assert completed.returncode != 0
    assert "accepted evidence" in completed.stderr
    assert "mismatch" in completed.stderr


def test_writer_rejects_manual_manifest_edit_instead_of_resealing(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["evidence_sets"] = []
    _write_json(manifest, payload)
    (repo / "evidence" / "new.json").write_text('{"value":"new"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/new.json")

    completed = _writer(repo, manifest)

    assert completed.returncode != 0
    assert "manifest must match HEAD before append" in completed.stderr


def test_writer_rejects_duplicate_evidence_set_name(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    (repo / "evidence" / "new.json").write_text('{"value":"new"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/new.json")

    completed = _writer(repo, manifest, name="accepted/old")

    assert completed.returncode != 0
    assert "accepted evidence set already exists" in completed.stderr


def test_writer_rejects_already_sealed_path(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)

    completed = _writer(repo, manifest, files=("evidence/old-a.json",))

    assert completed.returncode != 0
    assert "accepted evidence paths are already sealed" in completed.stderr


def test_writer_rejects_unindexed_candidate_file(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    (repo / "evidence" / "new.json").write_text('{"value":"new"}\n', encoding="utf-8")

    completed = _writer(repo, manifest)

    assert completed.returncode != 0
    assert "must have exactly one Git index entry" in completed.stderr


def test_writer_rejects_worktree_change_after_candidate_was_staged(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    candidate = repo / "evidence" / "new.json"
    candidate.write_text('{"value":"staged"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/new.json")
    candidate.write_text('{"value":"worktree"}\n', encoding="utf-8")

    completed = _writer(repo, manifest)

    assert completed.returncode != 0
    assert "index/worktree blob mismatch" in completed.stderr


def test_writer_rejects_duplicate_new_paths(tmp_path: Path) -> None:
    repo, manifest, _ = _init_repo(tmp_path)
    (repo / "evidence" / "new.json").write_text('{"value":"new"}\n', encoding="utf-8")
    _git(repo, "add", "evidence/new.json")

    completed = _writer(
        repo,
        manifest,
        files=("evidence/new.json", "evidence/new.json"),
    )

    assert completed.returncode != 0
    assert "duplicate new accepted evidence path" in completed.stderr
