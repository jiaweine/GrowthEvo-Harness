from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from verify_accepted_evidence_integrity import (
    SCHEMA_VERSION,
    _git,
    _safe_relative_path,
    _validate_manifest,
    verify_manifest,
)


_REGULAR_FILE_MODES = {"100644", "100755"}


def _normalize_files(files: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in files:
        relative = _safe_relative_path(raw)
        if relative in seen:
            raise ValueError(f"duplicate new accepted evidence path: {relative}")
        seen.add(relative)
        normalized.append(relative)
    if not normalized:
        raise ValueError("at least one new accepted evidence file is required")
    return tuple(sorted(normalized))


def _manifest_relative_path(*, repo_root: Path, manifest_path: Path) -> str:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(repo_root):
        raise ValueError("manifest path must stay under repository root")
    return _safe_relative_path(manifest_path.relative_to(repo_root).as_posix())


def _require_manifest_matches_head(*, repo_root: Path, manifest_path: Path) -> str:
    relative = _manifest_relative_path(repo_root=repo_root, manifest_path=manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing accepted evidence integrity manifest: {relative}")

    expected_blob = _git(repo_root, "rev-parse", f"HEAD:{relative}")
    observed_blob = _git(repo_root, "hash-object", "--stdin", input_bytes=manifest_path.read_bytes())
    if observed_blob != expected_blob:
        raise ValueError(
            "accepted evidence integrity manifest must match HEAD before append; "
            "manual edits or reseals are not allowed"
        )
    return relative


def _load_existing_manifest(*, repo_root: Path, manifest_path: Path) -> dict[str, object]:
    _require_manifest_matches_head(repo_root=repo_root, manifest_path=manifest_path)
    verify_manifest(repo_root=repo_root, manifest_path=manifest_path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid accepted evidence integrity JSON: {exc}") from exc
    _validate_manifest(payload)
    return payload


def _index_entry(*, repo_root: Path, relative: str) -> tuple[str, str]:
    output = _git(repo_root, "ls-files", "--stage", "--", relative)
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(
            f"new accepted evidence file must have exactly one Git index entry: {relative}"
        )
    try:
        metadata, indexed_path = lines[0].split("\t", 1)
        mode, blob_sha, stage = metadata.split()
    except ValueError as exc:
        raise ValueError(f"malformed Git index entry for accepted evidence file: {relative}") from exc
    if indexed_path != relative:
        raise ValueError(
            f"Git index path mismatch for accepted evidence file: {indexed_path!r} != {relative!r}"
        )
    if stage != "0":
        raise ValueError(f"new accepted evidence file must be a stage-0 Git index entry: {relative}")
    if mode not in _REGULAR_FILE_MODES:
        raise ValueError(f"new accepted evidence file must be a regular Git file: {relative}")
    return mode, blob_sha


def _build_new_file_entry(*, repo_root: Path, relative: str) -> dict[str, object]:
    path = (repo_root / relative).resolve()
    if not path.is_relative_to(repo_root):
        raise ValueError(f"accepted evidence path escapes repository root: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"missing new accepted evidence file: {relative}")
    data = path.read_bytes()
    if not data:
        raise ValueError(f"new accepted evidence file is empty: {relative}")

    _, index_blob = _index_entry(repo_root=repo_root, relative=relative)
    worktree_blob = _git(repo_root, "hash-object", "--stdin", input_bytes=data)
    if worktree_blob != index_blob:
        raise ValueError(
            f"new accepted evidence index/worktree blob mismatch for {relative}: "
            f"{index_blob} != {worktree_blob}"
        )
    return {
        "path": relative,
        "git_blob_sha": index_blob,
        "size_bytes": len(data),
    }


def append_evidence_set(
    *,
    repo_root: Path,
    manifest_path: Path,
    evidence_set_name: str,
    files: Iterable[str],
) -> dict[str, object]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path.resolve()
    manifest_relative = _manifest_relative_path(repo_root=repo_root, manifest_path=manifest_path)

    if not isinstance(evidence_set_name, str) or not evidence_set_name.strip():
        raise ValueError("new evidence set name must be a non-empty string")
    if evidence_set_name != evidence_set_name.strip():
        raise ValueError("new evidence set name must not have leading or trailing whitespace")

    normalized_files = _normalize_files(files)
    if manifest_relative in normalized_files:
        raise ValueError("accepted evidence seal manifest cannot seal itself")

    manifest = _load_existing_manifest(repo_root=repo_root, manifest_path=manifest_path)
    evidence_sets = manifest["evidence_sets"]
    assert isinstance(evidence_sets, list)

    existing_names = {str(evidence_set["name"]) for evidence_set in evidence_sets}
    if evidence_set_name in existing_names:
        raise ValueError(f"accepted evidence set already exists: {evidence_set_name}")

    existing_paths = {
        str(entry["path"])
        for evidence_set in evidence_sets
        for entry in evidence_set["files"]
    }
    overlap = sorted(existing_paths.intersection(normalized_files))
    if overlap:
        raise ValueError(f"accepted evidence paths are already sealed: {overlap}")

    new_files = [
        _build_new_file_entry(repo_root=repo_root, relative=relative)
        for relative in normalized_files
    ]
    evidence_sets.append({"name": evidence_set_name, "files": new_files})
    evidence_sets.sort(key=lambda evidence_set: str(evidence_set["name"]))

    object_format, _ = _validate_manifest(manifest)
    actual_object_format = _git(repo_root, "rev-parse", "--show-object-format")
    if object_format != actual_object_format:
        raise ValueError(
            f"git object format mismatch: repository={actual_object_format}, manifest={object_format}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported accepted evidence schema: {manifest.get('schema_version')!r}")

    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Append one new, explicitly indexed evidence set to the accepted-evidence Git-blob seal. "
            "Existing sealed evidence and the starting seal must still match HEAD exactly."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/accepted-evidence-integrity.v1.json"),
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("files", nargs="+")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo_root = args.repo_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = repo_root / manifest_path
    result = append_evidence_set(
        repo_root=repo_root,
        manifest_path=manifest_path,
        evidence_set_name=args.name,
        files=args.files,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
