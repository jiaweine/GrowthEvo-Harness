from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from write_evidence_integrity_manifest import SCHEMA_VERSION, build_manifest, _normalize_files


_TOP_LEVEL_KEYS = {
    "schema_version",
    "hash_algorithm",
    "file_count",
    "total_size_bytes",
    "files",
}
_ENTRY_KEYS = {"path", "sha256", "size_bytes"}


def _require_exact_keys(value: dict[str, Any], *, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _validate_manifest_structure(manifest: object) -> tuple[str, ...]:
    if not isinstance(manifest, dict):
        raise ValueError("integrity manifest must be a JSON object")
    _require_exact_keys(manifest, expected=_TOP_LEVEL_KEYS, label="integrity manifest")

    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported integrity manifest schema: {manifest['schema_version']!r}"
        )
    if manifest["hash_algorithm"] != "sha256":
        raise ValueError("integrity manifest hash_algorithm must be 'sha256'")

    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("integrity manifest files must be a non-empty list")

    paths: list[str] = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise ValueError(f"integrity manifest files[{index}] must be an object")
        _require_exact_keys(entry, expected=_ENTRY_KEYS, label=f"files[{index}]")

        path = entry["path"]
        digest = entry["sha256"]
        size = entry["size_bytes"]
        if not isinstance(path, str):
            raise ValueError(f"files[{index}].path must be a string")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"files[{index}].sha256 must be a 64-character string")
        try:
            bytes.fromhex(digest)
        except ValueError as exc:
            raise ValueError(f"files[{index}].sha256 must be hexadecimal") from exc
        if digest != digest.lower():
            raise ValueError(f"files[{index}].sha256 must use lowercase hexadecimal")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"files[{index}].size_bytes must be a positive integer")
        paths.append(path)

    normalized = _normalize_files(paths)
    if tuple(paths) != normalized:
        raise ValueError("integrity manifest file paths must be unique and canonically sorted")

    file_count = manifest["file_count"]
    total_size = manifest["total_size_bytes"]
    if not isinstance(file_count, int) or isinstance(file_count, bool):
        raise ValueError("integrity manifest file_count must be an integer")
    if file_count != len(files):
        raise ValueError(
            f"integrity manifest file_count mismatch: {file_count} != {len(files)}"
        )
    if not isinstance(total_size, int) or isinstance(total_size, bool) or total_size <= 0:
        raise ValueError("integrity manifest total_size_bytes must be a positive integer")
    declared_total = sum(entry["size_bytes"] for entry in files)
    if total_size != declared_total:
        raise ValueError(
            f"integrity manifest total_size_bytes mismatch: {total_size} != {declared_total}"
        )

    return normalized


def verify_manifest(*, root: Path, manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid integrity manifest JSON: {exc}") from exc

    paths = _validate_manifest_structure(manifest)
    actual = build_manifest(root=root, files=paths)
    if manifest != actual:
        expected_by_path = {entry["path"]: entry for entry in manifest["files"]}
        actual_by_path = {entry["path"]: entry for entry in actual["files"]}
        mismatches: list[str] = []
        for path in paths:
            expected = expected_by_path[path]
            observed = actual_by_path[path]
            if expected["size_bytes"] != observed["size_bytes"]:
                mismatches.append(
                    f"{path}: size {observed['size_bytes']} != {expected['size_bytes']}"
                )
            if expected["sha256"] != observed["sha256"]:
                mismatches.append(f"{path}: sha256 mismatch")
        if not mismatches:
            mismatches.append("manifest metadata does not match recomputed evidence")
        raise ValueError("evidence integrity verification failed: " + "; ".join(mismatches))
    return actual


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify every file listed by a GrowthEvo evidence integrity manifest."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    verified = verify_manifest(root=args.root, manifest_path=args.manifest)
    print(json.dumps(verified, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
