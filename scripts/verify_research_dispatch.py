#!/usr/bin/env python3
"""Verify that a manual full-data research run uses reviewed, CI-green main history."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any
import urllib.error
import urllib.request


SCHEMA_VERSION = "growthevo.research-dispatch.v1"
_REQUIRED_CI_JOBS = (
    "test (3.11)",
    "test (3.12)",
    "test (3.13)",
    "test (3.14)",
    "package",
    "obd-integration",
)
_CI_WORKFLOW_NAME = "GrowthEvo CI"
_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"


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


def _github_json(path: str) -> Any:
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GrowthEvo-Harness/research-dispatch-guard",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{api_url}/{path.lstrip('/')}",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed for {path}: HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed for {path}: {exc.reason}") from exc


def _verify_reviewed_pr_and_ci(
    *,
    repository: str,
    expected_sha: str,
    trusted_branch: str,
) -> dict[str, object]:
    pulls = _github_json(
        f"repos/{repository}/commits/{expected_sha}/pulls?per_page=100"
    )
    if not isinstance(pulls, list):
        raise RuntimeError("GitHub associated-pulls response must be a list")

    matching = [
        pull
        for pull in pulls
        if isinstance(pull, dict)
        and pull.get("merged_at")
        and pull.get("merge_commit_sha") == expected_sha
        and isinstance(pull.get("base"), dict)
        and pull["base"].get("ref") == trusted_branch
    ]
    if len(matching) != 1:
        raise RuntimeError(
            f"dispatch commit {expected_sha} must be the merge commit of exactly one "
            f"merged PR into {trusted_branch}; found {len(matching)}"
        )
    pull = matching[0]
    head = pull.get("head")
    if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
        raise RuntimeError("reviewed pull request is missing its head SHA")
    head_sha = head["sha"]

    runs_payload = _github_json(
        f"repos/{repository}/actions/runs"
        f"?head_sha={head_sha}&event=pull_request&per_page=100"
    )
    if not isinstance(runs_payload, dict) or not isinstance(
        runs_payload.get("workflow_runs"), list
    ):
        raise RuntimeError("GitHub workflow-runs response is malformed")
    matching_runs = [
        run
        for run in runs_payload["workflow_runs"]
        if isinstance(run, dict)
        and run.get("head_sha") == head_sha
        and run.get("event") == "pull_request"
        and run.get("name") == _CI_WORKFLOW_NAME
        and run.get("path") == _CI_WORKFLOW_PATH
    ]
    if not matching_runs:
        raise RuntimeError(
            f"reviewed PR head {head_sha} has no {_CI_WORKFLOW_NAME} pull-request run"
        )
    ci_run = max(
        matching_runs,
        key=lambda run: (
            int(run.get("run_attempt") or 0),
            int(run.get("id") or 0),
        ),
    )
    if ci_run.get("status") != "completed" or ci_run.get("conclusion") != "success":
        raise RuntimeError(
            f"latest {_CI_WORKFLOW_NAME} run for reviewed PR head {head_sha} "
            f"is not successful: status={ci_run.get('status')!r}, "
            f"conclusion={ci_run.get('conclusion')!r}"
        )
    run_id = ci_run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise RuntimeError("reviewed CI run is missing a numeric run id")

    jobs_payload = _github_json(
        f"repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
    )
    if not isinstance(jobs_payload, dict) or not isinstance(jobs_payload.get("jobs"), list):
        raise RuntimeError("GitHub workflow-jobs response is malformed")

    jobs_by_name: dict[str, list[dict[str, Any]]] = {}
    for job in jobs_payload["jobs"]:
        if not isinstance(job, dict):
            continue
        name = job.get("name")
        if isinstance(name, str):
            jobs_by_name.setdefault(name, []).append(job)

    verified_jobs: list[dict[str, object]] = []
    for name in _REQUIRED_CI_JOBS:
        jobs = jobs_by_name.get(name, [])
        if len(jobs) != 1:
            raise RuntimeError(
                f"reviewed CI run {run_id} must contain exactly one latest job named "
                f"{name!r}; found {len(jobs)}"
            )
        job = jobs[0]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise RuntimeError(
                f"reviewed CI job {name!r} is not successful: "
                f"status={job.get('status')!r}, conclusion={job.get('conclusion')!r}"
            )
        verified_jobs.append(
            {
                "name": name,
                "job_id": job.get("id"),
                "status": "completed",
                "conclusion": "success",
            }
        )

    number = pull.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise RuntimeError("reviewed pull request is missing a numeric PR number")
    return {
        "reviewed_pull_request_number": number,
        "reviewed_pull_request_url": pull.get("html_url"),
        "reviewed_pull_request_head_sha": head_sha,
        "reviewed_pull_request_merge_sha": expected_sha,
        "reviewed_pull_request_base_ref": trusted_branch,
        "reviewed_ci_workflow_name": _CI_WORKFLOW_NAME,
        "reviewed_ci_workflow_path": _CI_WORKFLOW_PATH,
        "reviewed_ci_run_id": run_id,
        "reviewed_ci_run_attempt": ci_run.get("run_attempt"),
        "reviewed_ci_jobs": verified_jobs,
        "reviewed_ci_verified": True,
    }


def verify_dispatch(
    *,
    trusted_ref: str,
    trusted_branch: str,
    reason: str,
) -> dict[str, object]:
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

    workflow_sha = _required_env("GITHUB_WORKFLOW_SHA")
    if workflow_sha != expected_sha:
        raise RuntimeError(
            f"workflow commit {workflow_sha} does not match evidence commit {expected_sha}"
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

    repository = _required_env("GITHUB_REPOSITORY")
    review = _verify_reviewed_pr_and_ci(
        repository=repository,
        expected_sha=expected_sha,
        trusted_branch=trusted_branch,
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_reason": reason,
        "repository": repository,
        "event_name": _required_env("GITHUB_EVENT_NAME"),
        "actor": _required_env("GITHUB_ACTOR"),
        "triggering_actor": os.environ.get("GITHUB_TRIGGERING_ACTOR", "").strip() or None,
        "workflow": _required_env("GITHUB_WORKFLOW"),
        "workflow_ref": _required_env("GITHUB_WORKFLOW_REF"),
        "workflow_sha": workflow_sha,
        "workflow_sha_matches_commit": True,
        "ref": _required_env("GITHUB_REF"),
        "ref_name": _required_env("GITHUB_REF_NAME"),
        "commit_sha": expected_sha,
        "run_id": _required_env("GITHUB_RUN_ID"),
        "run_attempt": _required_env("GITHUB_RUN_ATTEMPT"),
        "trusted_ref": trusted_ref,
        "trusted_branch": trusted_branch,
        "trusted_ref_sha_at_dispatch": trusted_sha,
        "commit_is_trusted_ref_ancestor": True,
        **review,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trusted-ref", default="origin/main")
    parser.add_argument("--trusted-branch", default="main")
    parser.add_argument(
        "--reason",
        default=os.environ.get("EXPERIMENT_REASON", ""),
        help="Preregistered experiment or evidence-rerun reason.",
    )
    args = parser.parse_args()

    payload = verify_dispatch(
        trusted_ref=args.trusted_ref,
        trusted_branch=args.trusted_branch,
        reason=args.reason,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
