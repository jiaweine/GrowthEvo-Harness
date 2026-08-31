from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any


SCHEMA_VERSION = "growthevo.accepted-evidence-integrity.v1"
_TOP_LEVEL_KEYS = {"schema_version", "git_object_format", "evidence_sets"}
_SET_KEYS = {"name", "files"}
_FILE_KEYS = {"path", "git_blob_sha", "size_bytes"}


def _git(repo_root: Path, *args: str, input_bytes: bytes | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {stderr}")
    return completed.stdout.decode("utf-8").strip()


def _require_exact_keys(value: dict[str, Any], *, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _safe_relative_path(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("accepted evidence path must be a string")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"accepted evidence path must stay under repository root: {raw}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError("accepted evidence path must name a file")
    return normalized


def _validate_manifest(manifest: object) -> tuple[str, tuple[dict[str, object], ...]]:
    if not isinstance(manifest, dict):
        raise ValueError("accepted evidence integrity manifest must be a JSON object")
    _require_exact_keys(manifest, expected=_TOP_LEVEL_KEYS, label="manifest")

    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported accepted evidence schema: {manifest['schema_version']!r}")
    object_format = manifest["git_object_format"]
    if object_format not in {"sha1", "sha256"}:
        raise ValueError("git_object_format must be 'sha1' or 'sha256'")
    expected_sha_length = 40 if object_format == "sha1" else 64

    evidence_sets = manifest["evidence_sets"]
    if not isinstance(evidence_sets, list) or not evidence_sets:
        raise ValueError("evidence_sets must be a non-empty list")

    set_names: list[str] = []
    all_paths: set[str] = set()
    entries: list[dict[str, object]] = []
    for set_index, evidence_set in enumerate(evidence_sets):
        if not isinstance(evidence_set, dict):
            raise ValueError(f"evidence_sets[{set_index}] must be an object")
        _require_exact_keys(evidence_set, expected=_SET_KEYS, label=f"evidence_sets[{set_index}]")
        name = evidence_set["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"evidence_sets[{set_index}].name must be a non-empty string")
        set_names.append(name)

        files = evidence_set["files"]
        if not isinstance(files, list) or not files:
            raise ValueError(f"evidence_sets[{set_index}].files must be a non-empty list")
        paths_in_set: list[str] = []
        for file_index, entry in enumerate(files):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"evidence_sets[{set_index}].files[{file_index}] must be an object"
                )
            _require_exact_keys(
                entry,
                expected=_FILE_KEYS,
                label=f"evidence_sets[{set_index}].files[{file_index}]",
            )
            path = _safe_relative_path(entry["path"])
            blob_sha = entry["git_blob_sha"]
            size = entry["size_bytes"]
            if not isinstance(blob_sha, str) or len(blob_sha) != expected_sha_length:
                raise ValueError(
                    f"{path}: git_blob_sha must be {expected_sha_length} hexadecimal characters"
                )
            try:
                bytes.fromhex(blob_sha)
            except ValueError as exc:
                raise ValueError(f"{path}: git_blob_sha must be hexadecimal") from exc
            if blob_sha != blob_sha.lower():
                raise ValueError(f"{path}: git_blob_sha must use lowercase hexadecimal")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise ValueError(f"{path}: size_bytes must be a positive integer")
            if path in all_paths:
                raise ValueError(f"duplicate accepted evidence path: {path}")
            all_paths.add(path)
            paths_in_set.append(path)
            entries.append(
                {
                    "evidence_set": name,
                    "path": path,
                    "git_blob_sha": blob_sha,
                    "size_bytes": size,
                }
            )
        if paths_in_set != sorted(paths_in_set):
            raise ValueError(f"evidence set {name!r} file paths must be canonically sorted")

    if len(set_names) != len(set(set_names)):
        raise ValueError("evidence set names must be unique")
    if set_names != sorted(set_names):
        raise ValueError("evidence set names must be canonically sorted")
    return object_format, tuple(entries)


def verify_manifest(*, repo_root: Path, manifest_path: Path) -> dict[str, object]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(repo_root):
        raise ValueError("manifest path must stay under repository root")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid accepted evidence integrity JSON: {exc}") from exc

    object_format, entries = _validate_manifest(manifest)
    actual_object_format = _git(repo_root, "rev-parse", "--show-object-format")
    if actual_object_format != object_format:
        raise ValueError(
            f"git object format mismatch: repository={actual_object_format}, manifest={object_format}"
        )

    verified: list[dict[str, object]] = []
    for entry in entries:
        relative = str(entry["path"])
        expected_blob = str(entry["git_blob_sha"])
        expected_size = int(entry["size_bytes"])
        path = (repo_root / relative).resolve()
        if not path.is_relative_to(repo_root):
            raise ValueError(f"accepted evidence path escapes repository root: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"missing accepted evidence file: {relative}")

        data = path.read_bytes()
        observed_size = len(data)
        if observed_size != expected_size:
            raise ValueError(
                f"accepted evidence size mismatch for {relative}: {observed_size} != {expected_size}"
            )

        committed_blob = _git(repo_root, "rev-parse", f"HEAD:{relative}")
        if committed_blob != expected_blob:
            raise ValueError(
                f"accepted evidence committed blob mismatch for {relative}: "
                f"{committed_blob} != {expected_blob}"
            )

        worktree_blob = _git(repo_root, "hash-object", "--stdin", input_bytes=data)
        if worktree_blob != expected_blob:
            raise ValueError(
                f"accepted evidence worktree blob mismatch for {relative}: "
                f"{worktree_blob} != {expected_blob}"
            )

        verified.append(
            {
                "evidence_set": entry["evidence_set"],
                "path": relative,
                "git_blob_sha": expected_blob,
                "size_bytes": expected_size,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "git_object_format": object_format,
        "file_count": len(verified),
        "verified_files": verified,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail closed if committed or worktree accepted full-data evidence differs from its seal."
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/accepted-evidence-integrity.v1.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo_root = args.repo_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = repo_root / manifest_path
    result = verify_manifest(repo_root=repo_root, manifest_path=manifest_path)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
