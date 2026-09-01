from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_evidence_integrity_manifest import verify_manifest


_SHA256_PREFIX = "sha256:"


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _safe_relative_path(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty string")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must stay under its evidence root: {raw!r}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"{label} must name a file")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_prefixed_sha256(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or not raw.startswith(_SHA256_PREFIX):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    digest = raw[len(_SHA256_PREFIX) :]
    if len(digest) != 64 or digest != digest.lower():
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>") from exc
    return digest


def _source_entry_for_key(
    logical_name: str,
    *,
    entries: tuple[dict[str, object], ...],
) -> dict[str, object]:
    if "/" in logical_name:
        matches = [entry for entry in entries if entry["path"] == logical_name]
    else:
        matches = [
            entry
            for entry in entries
            if Path(str(entry["path"])).name == logical_name
        ]
    if not matches:
        raise ValueError(f"metadata source file is not covered by the integrity manifest: {logical_name}")
    if len(matches) != 1:
        paths = sorted(str(entry["path"]) for entry in matches)
        raise ValueError(
            f"metadata source file is ambiguous in the integrity manifest: {logical_name}: {paths}"
        )
    return matches[0]


def _load_copy_contract(metadata: dict[str, Any]) -> tuple[dict[str, object], dict[str, object]]:
    source_hashes = metadata.get("source_artifact_file_sha256")
    copy_formats = metadata.get("persisted_copy_format")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("metadata source_artifact_file_sha256 must be a non-empty object")
    if not isinstance(copy_formats, dict) or not copy_formats:
        raise ValueError("metadata persisted_copy_format must be a non-empty object")
    if set(source_hashes) != set(copy_formats):
        raise ValueError(
            "metadata source_artifact_file_sha256 and persisted_copy_format must name the same files"
        )
    return source_hashes, copy_formats


def _assert_json_equal(source: Path, persisted: Path, *, logical_name: str) -> None:
    try:
        source_value = json.loads(source.read_text(encoding="utf-8"))
        persisted_value = json.loads(persisted.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{logical_name}: content-preserving copy must contain valid JSON") from exc
    if source_value != persisted_value:
        raise ValueError(f"{logical_name}: persisted JSON content differs from source artifact")


def _verify_evidence_commit(metadata: dict[str, Any], *, persisted_root: Path) -> str:
    evidence_commit = metadata.get("evidence_commit_sha")
    if not isinstance(evidence_commit, str) or len(evidence_commit) != 40:
        raise ValueError("metadata evidence_commit_sha must be a 40-character Git SHA")
    try:
        bytes.fromhex(evidence_commit)
    except ValueError as exc:
        raise ValueError("metadata evidence_commit_sha must be hexadecimal") from exc

    locked_result = persisted_root / "locked-result.json"
    if locked_result.is_file():
        result = _load_json(locked_result, label="persisted locked-result")
        artifact = result.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("commit_sha") != evidence_commit:
            raise ValueError("persisted locked-result commit_sha does not match metadata evidence_commit_sha")

    source_provenance = persisted_root / "source-provenance.json"
    if source_provenance.is_file():
        provenance = _load_json(source_provenance, label="persisted source-provenance")
        recorded = provenance.get("growth_evo_commit_sha")
        if recorded is not None and recorded != evidence_commit:
            raise ValueError(
                "persisted source-provenance growth_evo_commit_sha does not match metadata evidence_commit_sha"
            )
    return evidence_commit


def verify_acceptance(
    *,
    source_root: Path,
    integrity_manifest: Path,
    persisted_root: Path,
    metadata_path: Path,
) -> dict[str, object]:
    source_root = source_root.resolve()
    integrity_manifest = integrity_manifest.resolve()
    persisted_root = persisted_root.resolve()
    metadata_path = metadata_path.resolve()

    verified_manifest = verify_manifest(root=source_root, manifest_path=integrity_manifest)
    manifest_entries = tuple(verified_manifest["files"])
    metadata = _load_json(metadata_path, label="evidence metadata")
    source_hashes, copy_formats = _load_copy_contract(metadata)

    workflow_digest = metadata.get("workflow_artifact_digest")
    if workflow_digest is not None:
        _validate_prefixed_sha256(workflow_digest, label="metadata workflow_artifact_digest")

    verified_files: list[dict[str, object]] = []
    for raw_name in sorted(source_hashes):
        logical_name = _safe_relative_path(raw_name, label="metadata source file name")
        expected_digest = _validate_prefixed_sha256(
            source_hashes[raw_name],
            label=f"metadata source SHA256 for {logical_name}",
        )
        entry = _source_entry_for_key(logical_name, entries=manifest_entries)
        source_relative = str(entry["path"])
        manifest_digest = str(entry["sha256"])
        if expected_digest != manifest_digest:
            raise ValueError(
                f"{logical_name}: metadata source SHA256 does not match verified integrity manifest"
            )

        source_path = (source_root / source_relative).resolve()
        if not source_path.is_relative_to(source_root):
            raise ValueError(f"source manifest path escapes source root: {source_relative}")

        mode = copy_formats[raw_name]
        if not isinstance(mode, str) or not mode.strip():
            raise ValueError(f"{logical_name}: persisted copy format must be a non-empty string")
        normalized_mode = mode.strip().lower()
        persisted_path = (persisted_root / logical_name).resolve()
        if not persisted_path.is_relative_to(persisted_root):
            raise ValueError(f"persisted path escapes persisted root: {logical_name}")

        if normalized_mode.startswith("byte-identical"):
            if not persisted_path.is_file():
                raise FileNotFoundError(f"missing byte-identical persisted evidence file: {logical_name}")
            if persisted_path.stat().st_size != int(entry["size_bytes"]):
                raise ValueError(f"{logical_name}: persisted byte-identical copy size differs from source")
            if _sha256(persisted_path) != manifest_digest:
                raise ValueError(f"{logical_name}: persisted byte-identical copy SHA256 differs from source")
            outcome = "byte-identical"
        elif normalized_mode.startswith("content-preserving compact json"):
            if not persisted_path.is_file():
                raise FileNotFoundError(f"missing content-preserving persisted evidence file: {logical_name}")
            _assert_json_equal(source_path, persisted_path, logical_name=logical_name)
            outcome = "json-semantic-identical"
        elif normalized_mode.startswith("not persisted"):
            if persisted_path.exists():
                raise ValueError(f"{logical_name}: metadata declares not persisted but a persisted file exists")
            outcome = "source-only"
        else:
            raise ValueError(f"{logical_name}: unsupported persisted copy format: {mode!r}")

        verified_files.append(
            {
                "logical_name": logical_name,
                "source_path": source_relative,
                "source_sha256": _SHA256_PREFIX + manifest_digest,
                "copy_mode": outcome,
            }
        )

    evidence_commit = _verify_evidence_commit(metadata, persisted_root=persisted_root)
    return {
        "schema_version": "growthevo.evidence-acceptance-verification.v1",
        "evidence_commit_sha": evidence_commit,
        "source_integrity_schema": verified_manifest["schema_version"],
        "verified_source_file_count": len(verified_manifest["files"]),
        "accepted_file_count": len(verified_files),
        "verified_files": verified_files,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the handoff from a hashed full-data workflow artifact into a persisted "
            "accepted-evidence directory."
        )
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--integrity-manifest", required=True, type=Path)
    parser.add_argument("--persisted-root", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = verify_acceptance(
        source_root=args.source_root,
        integrity_manifest=args.integrity_manifest,
        persisted_root=args.persisted_root,
        metadata_path=args.metadata,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
