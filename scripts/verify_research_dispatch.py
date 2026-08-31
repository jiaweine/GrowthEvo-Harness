#!/usr/bin/env python3
"""Verify that a manual full-data research run uses reviewed main history."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


SCHEMA_VERSION = "growthevo.research-dispatch.v1"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable {name} is missing")
    return value


def _git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def verify_dispatch(*, trusted_ref: str, reason: str) -> dict[str, object]:
    if _required_env("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise RuntimeError("full-data research guard only accepts workflow_dispatch runs")

    reason = reason.strip()
    if not reason:
        raise RuntimeError("experiment reason must be non-empty")

    expected_sha = _required_env("GITHUB_SHA")
    checked_out_sha = _git_output("rev-parse", "HEAD")
    if checked_out_sha != expected_sha:
        raise RuntimeError(
            f"checked-out commit {checked_out_sha} does not match GITHUB_SHA {expected_sha}"
        )

    trusted_sha = _git_output("rev-parse", f"{trusted_ref}^{{commit}}")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_sha, trusted_ref],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if ancestry.returncode == 1:
        raise RuntimeError(
            f"dispatch commit {expected_sha} is not part of trusted main history ({trusted_ref})"
        )
    if ancestry.returncode != 0:
        raise RuntimeError(
            f"could not verify dispatch commit ancestry against {trusted_ref}: "
            f"{ancestry.stderr.strip()}"
        )

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_reason": reason,
        "repository": _required_env("GITHUB_REPOSITORY"),
        "event_name": _required_env("GITHUB_EVENT_NAME"),
        "actor": _required_env("GITHUB_ACTOR"),
        "triggering_actor": os.environ.get("GITHUB_TRIGGERING_ACTOR", "").strip() or None,
        "workflow": _required_env("GITHUB_WORKFLOW"),
        "workflow_ref": _required_env("GITHUB_WORKFLOW_REF"),
        "workflow_sha": _required_env("GITHUB_WORKFLOW_SHA"),
        "ref": _required_env("GITHUB_REF"),
        "ref_name": _required_env("GITHUB_REF_NAME"),
        "commit_sha": expected_sha,
        "run_id": _required_env("GITHUB_RUN_ID"),
        "run_attempt": _required_env("GITHUB_RUN_ATTEMPT"),
        "trusted_ref": trusted_ref,
        "trusted_ref_sha_at_dispatch": trusted_sha,
        "commit_is_trusted_ref_ancestor": True,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trusted-ref", default="origin/main")
    parser.add_argument(
        "--reason",
        default=os.environ.get("EXPERIMENT_REASON", ""),
        help="Preregistered experiment or evidence-rerun reason.",
    )
    args = parser.parse_args()

    payload = verify_dispatch(trusted_ref=args.trusted_ref, reason=args.reason)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
