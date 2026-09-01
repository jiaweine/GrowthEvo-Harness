from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from verify_research_dispatch import _github_json


_SCHEMA_VERSION = "growthevo.evidence-artifact-identity-verification.v1"
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PLATFORM_POLICY_BY_EVIDENCE_SCHEMA = {
    "growthevo.criteo-evidence-record.v1": {
        "workflow_path": ".github/workflows/full-criteo-pr-validation.yml",
        "artifact_name": "criteo-full-preregistered-evidence",
    },
    "growthevo.obd-evidence-record.v1": {
        "workflow_path": ".github/workflows/full-obd-pr-validation.yml",
        "artifact_name": "obd-full-preregistered-evidence",
    },
}


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid evidence metadata JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("evidence metadata must be a JSON object")
    return value


def _positive_int(raw: object, *, label: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return raw


def _git_sha(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or len(raw) != 40 or raw != raw.lower():
        raise ValueError(f"{label} must be a 40-character lowercase hexadecimal Git SHA")
    try:
        bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a 40-character lowercase hexadecimal Git SHA") from exc
    return raw


def _artifact_digest(raw: object) -> str:
    if not isinstance(raw, str) or _SHA256_PATTERN.fullmatch(raw) is None:
        raise ValueError("metadata workflow_artifact_digest must use sha256:<64 lowercase hex>")
    return raw


def _repository(raw: str) -> str:
    if _REPOSITORY_PATTERN.fullmatch(raw) is None:
        raise ValueError("repository must use owner/name with GitHub-safe characters")
    return raw


def _platform_policy(metadata: dict[str, Any]) -> tuple[str, str, str]:
    schema_version = metadata.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError("metadata schema_version must be a non-empty string")
    policy = _PLATFORM_POLICY_BY_EVIDENCE_SCHEMA.get(schema_version)
    if policy is None:
        raise ValueError(
            "unsupported evidence metadata schema_version for platform verification: "
            f"{schema_version!r}"
        )
    return schema_version, policy["workflow_path"], policy["artifact_name"]


def _require_object(raw: object, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"GitHub {label} response must be a JSON object")
    return raw


def verify_artifact_identity(
    *,
    metadata_path: Path,
    repository: str,
) -> dict[str, object]:
    metadata = _load_metadata(metadata_path)
    repository = _repository(repository)
    evidence_schema_version, expected_workflow_path, expected_artifact_name = _platform_policy(
        metadata
    )

    evidence_commit = _git_sha(
        metadata.get("evidence_commit_sha"),
        label="metadata evidence_commit_sha",
    )
    workflow_run_id = _positive_int(
        metadata.get("workflow_run_id"),
        label="metadata workflow_run_id",
    )
    workflow_artifact_id = _positive_int(
        metadata.get("workflow_artifact_id"),
        label="metadata workflow_artifact_id",
    )
    workflow_artifact_digest = _artifact_digest(metadata.get("workflow_artifact_digest"))

    run = _require_object(
        _github_json(f"repos/{repository}/actions/runs/{workflow_run_id}"),
        label="workflow-run",
    )
    if run.get("id") != workflow_run_id:
        raise RuntimeError("GitHub workflow run ID does not match evidence metadata")
    run_repository = run.get("repository")
    if not isinstance(run_repository, dict) or run_repository.get("full_name") != repository:
        raise RuntimeError("GitHub workflow run repository does not match requested repository")
    if run.get("event") != "workflow_dispatch":
        raise RuntimeError("GitHub workflow run must have event=workflow_dispatch for future acceptance")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise RuntimeError(
            "GitHub workflow run is not a completed success: "
            f"status={run.get('status')!r}, conclusion={run.get('conclusion')!r}"
        )
    if run.get("head_sha") != evidence_commit:
        raise RuntimeError("GitHub workflow run head_sha does not match metadata evidence_commit_sha")
    if run.get("path") != expected_workflow_path:
        raise RuntimeError(
            "GitHub workflow run path does not match evidence-schema platform policy: "
            f"{run.get('path')!r} != {expected_workflow_path!r}"
        )

    artifact = _require_object(
        _github_json(f"repos/{repository}/actions/artifacts/{workflow_artifact_id}"),
        label="artifact",
    )
    if artifact.get("id") != workflow_artifact_id:
        raise RuntimeError("GitHub artifact ID does not match evidence metadata")
    if artifact.get("name") != expected_artifact_name:
        raise RuntimeError(
            "GitHub artifact name does not match evidence-schema platform policy: "
            f"{artifact.get('name')!r} != {expected_artifact_name!r}"
        )
    if artifact.get("expired") is not False:
        raise RuntimeError("GitHub evidence artifact is expired or has unknown expiration state")
    if artifact.get("digest") != workflow_artifact_digest:
        raise RuntimeError("GitHub artifact digest does not match metadata workflow_artifact_digest")

    artifact_run = artifact.get("workflow_run")
    if not isinstance(artifact_run, dict):
        raise RuntimeError("GitHub artifact is missing workflow_run provenance")
    if artifact_run.get("id") != workflow_run_id:
        raise RuntimeError("GitHub artifact does not belong to metadata workflow_run_id")
    if artifact_run.get("head_sha") != evidence_commit:
        raise RuntimeError("GitHub artifact workflow_run head_sha does not match evidence commit")

    run_repository_id = run_repository.get("id")
    artifact_repository_id = artifact_run.get("repository_id")
    if (
        isinstance(run_repository_id, bool)
        or not isinstance(run_repository_id, int)
        or isinstance(artifact_repository_id, bool)
        or not isinstance(artifact_repository_id, int)
        or artifact_repository_id != run_repository_id
    ):
        raise RuntimeError("GitHub artifact workflow_run repository identity does not match workflow run")

    return {
        "schema_version": _SCHEMA_VERSION,
        "evidence_schema_version": evidence_schema_version,
        "repository": repository,
        "evidence_commit_sha": evidence_commit,
        "workflow_run_id": workflow_run_id,
        "workflow_path": expected_workflow_path,
        "workflow_event": "workflow_dispatch",
        "workflow_status": "completed",
        "workflow_conclusion": "success",
        "workflow_artifact_id": workflow_artifact_id,
        "workflow_artifact_name": expected_artifact_name,
        "workflow_artifact_digest": workflow_artifact_digest,
        "workflow_artifact_expired": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that evidence metadata names the exact successful GitHub Actions run and "
            "artifact required by its committed evidence schema. This is a future-acceptance "
            "check and does not download, promote, or modify evidence."
        )
    )
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = verify_artifact_identity(
        metadata_path=args.metadata,
        repository=args.repository,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
