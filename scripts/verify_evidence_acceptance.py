from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_evidence_integrity_manifest import verify_manifest


_SHA256_PREFIX = "sha256:"
_DISPATCH_SCHEMA_VERSION = "growthevo.research-dispatch.v1"


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _safe_filename(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty filename")
    path = Path(raw)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or path.name in {"", ".", ".."}
        or raw != path.name
    ):
        raise ValueError(f"{label} must be one logical filename without directories: {raw!r}")
    return path.name


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


def _validate_git_sha(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or len(raw) != 40 or raw != raw.lower():
        raise ValueError(f"{label} must be a 40-character lowercase hexadecimal Git SHA")
    try:
        bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a 40-character lowercase hexadecimal Git SHA") from exc
    return raw


def _positive_int(raw: object, *, label: str, allow_decimal_string: bool = False) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{label} must be a positive integer")
    if isinstance(raw, int):
        value = raw
    elif allow_decimal_string and isinstance(raw, str) and raw.isdecimal():
        value = int(raw)
    else:
        raise ValueError(f"{label} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _manifest_entries_by_filename(
    entries: tuple[dict[str, object], ...],
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    duplicate_paths: dict[str, list[str]] = {}
    for entry in entries:
        path = str(entry["path"])
        name = Path(path).name
        if name in indexed:
            duplicate_paths.setdefault(name, [str(indexed[name]["path"])]).append(path)
        else:
            indexed[name] = entry
    if duplicate_paths:
        rendered = "; ".join(
            f"{name}: {sorted(paths)}" for name, paths in sorted(duplicate_paths.items())
        )
        raise ValueError(
            "source integrity manifest filenames must be unique for acceptance metadata: " + rendered
        )
    return indexed


def _load_copy_contract(
    metadata: dict[str, Any],
    *,
    expected_names: set[str],
) -> tuple[dict[str, object], dict[str, object]]:
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

    source_names = {_safe_filename(name, label="metadata source file name") for name in source_hashes}
    if source_names != expected_names:
        missing = sorted(expected_names - source_names)
        extra = sorted(source_names - expected_names)
        raise ValueError(
            "acceptance metadata must cover every source integrity-manifest file exactly once: "
            f"missing={missing}, extra={extra}"
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
    evidence_commit = _validate_git_sha(
        metadata.get("evidence_commit_sha"),
        label="metadata evidence_commit_sha",
    )

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


def _verify_dispatch_identity(
    *,
    source_root: Path,
    dispatch_entry: dict[str, object],
    metadata: dict[str, Any],
    evidence_commit: str,
) -> dict[str, object]:
    dispatch_relative = str(dispatch_entry["path"])
    dispatch_path = (source_root / dispatch_relative).resolve()
    if not dispatch_path.is_relative_to(source_root):
        raise ValueError(f"dispatch provenance path escapes source root: {dispatch_relative}")
    dispatch = _load_json(dispatch_path, label="source dispatch provenance")

    if dispatch.get("schema_version") != _DISPATCH_SCHEMA_VERSION:
        raise ValueError(
            "source dispatch provenance schema_version must be " + _DISPATCH_SCHEMA_VERSION
        )
    if dispatch.get("event_name") != "workflow_dispatch":
        raise ValueError("source dispatch provenance must record event_name=workflow_dispatch")
    for flag in (
        "workflow_sha_matches_commit",
        "commit_is_trusted_ref_ancestor",
        "reviewed_ci_verified",
    ):
        if dispatch.get(flag) is not True:
            raise ValueError(f"source dispatch provenance must record {flag}=true")

    for field in ("commit_sha", "workflow_sha", "reviewed_pull_request_merge_sha"):
        recorded = _validate_git_sha(
            dispatch.get(field),
            label=f"source dispatch provenance {field}",
        )
        if recorded != evidence_commit:
            raise ValueError(
                f"source dispatch provenance {field} does not match metadata evidence_commit_sha"
            )

    trusted_branch = dispatch.get("trusted_branch")
    reviewed_base = dispatch.get("reviewed_pull_request_base_ref")
    if not isinstance(trusted_branch, str) or not trusted_branch:
        raise ValueError("source dispatch provenance trusted_branch must be non-empty")
    if reviewed_base != trusted_branch:
        raise ValueError(
            "source dispatch provenance reviewed PR base does not match its trusted branch"
        )

    dispatch_run_id = _positive_int(
        dispatch.get("run_id"),
        label="source dispatch provenance run_id",
        allow_decimal_string=True,
    )
    metadata_run_id = _positive_int(
        metadata.get("workflow_run_id"),
        label="metadata workflow_run_id",
    )
    if metadata_run_id != dispatch_run_id:
        raise ValueError(
            "metadata workflow_run_id does not match source dispatch provenance run_id"
        )
    artifact_id = _positive_int(
        metadata.get("workflow_artifact_id"),
        label="metadata workflow_artifact_id",
    )

    reviewed_pr_number = _positive_int(
        dispatch.get("reviewed_pull_request_number"),
        label="source dispatch provenance reviewed_pull_request_number",
    )
    reviewed_ci_run_id = _positive_int(
        dispatch.get("reviewed_ci_run_id"),
        label="source dispatch provenance reviewed_ci_run_id",
    )
    return {
        "workflow_run_id": metadata_run_id,
        "workflow_artifact_id": artifact_id,
        "reviewed_pull_request_number": reviewed_pr_number,
        "reviewed_ci_run_id": reviewed_ci_run_id,
    }


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

    if not integrity_manifest.is_relative_to(source_root):
        raise ValueError("integrity manifest must be inside the extracted source artifact root")
    if not metadata_path.is_relative_to(persisted_root):
        raise ValueError("evidence metadata must be inside the persisted evidence root")

    verified_manifest = verify_manifest(root=source_root, manifest_path=integrity_manifest)
    manifest_entries = tuple(verified_manifest["files"])
    entries_by_name = _manifest_entries_by_filename(manifest_entries)
    dispatch_entry = entries_by_name.get("dispatch-provenance.json")
    if dispatch_entry is None:
        raise ValueError(
            "source integrity manifest must include dispatch-provenance.json for acceptance"
        )

    metadata = _load_json(metadata_path, label="evidence metadata")
    source_hashes, copy_formats = _load_copy_contract(
        metadata,
        expected_names=set(entries_by_name),
    )
    _validate_prefixed_sha256(
        metadata.get("workflow_artifact_digest"),
        label="metadata workflow_artifact_digest",
    )
    evidence_commit = _verify_evidence_commit(metadata, persisted_root=persisted_root)
    dispatch_identity = _verify_dispatch_identity(
        source_root=source_root,
        dispatch_entry=dispatch_entry,
        metadata=metadata,
        evidence_commit=evidence_commit,
    )

    verified_files: list[dict[str, object]] = []
    for raw_name in sorted(source_hashes):
        logical_name = _safe_filename(raw_name, label="metadata source file name")
        expected_digest = _validate_prefixed_sha256(
            source_hashes[raw_name],
            label=f"metadata source SHA256 for {logical_name}",
        )
        entry = entries_by_name[logical_name]
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

    return {
        "schema_version": "growthevo.evidence-acceptance-verification.v1",
        "evidence_commit_sha": evidence_commit,
        "source_integrity_schema": verified_manifest["schema_version"],
        "verified_source_file_count": len(verified_manifest["files"]),
        "accepted_file_count": len(verified_files),
        **dispatch_identity,
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
