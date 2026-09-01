from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_research_dispatch.py"
SPEC = importlib.util.spec_from_file_location("research_dispatch_cli_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str, value: str) -> str:
    (repo / "marker.txt").write_text(value, encoding="utf-8")
    _git(repo, "add", "marker.txt")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _env(sha: str) -> dict[str, str]:
    return {
        **os.environ,
        "EXPERIMENT_REASON": "explicit replication check",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": sha,
        "GITHUB_REPOSITORY": "example/GrowthEvo-Harness",
        "GITHUB_ACTOR": "researcher",
        "GITHUB_TRIGGERING_ACTOR": "researcher",
        "GITHUB_WORKFLOW": "Full Research Validation",
        "GITHUB_WORKFLOW_REF": "example/GrowthEvo-Harness/.github/workflows/full.yml@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": sha,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REF_NAME": "main",
        "GITHUB_RUN_ID": "123456",
        "GITHUB_RUN_ATTEMPT": "1",
    }


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI")
    first = _commit(repo, "first", "one\n")
    second = _commit(repo, "second", "two\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", second)
    return repo, first, second


def test_reviewed_historical_main_commit_is_allowed_and_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, first, second = _repo(tmp_path)
    _git(repo, "checkout", "--detach", first)
    monkeypatch.chdir(repo)
    for name, value in _env(first).items():
        monkeypatch.setenv(name, value)

    review = {
        "reviewed_pull_request_number": 80,
        "reviewed_pull_request_url": "https://github.com/example/GrowthEvo-Harness/pull/80",
        "reviewed_pull_request_head_sha": "a" * 40,
        "reviewed_pull_request_merge_sha": first,
        "reviewed_pull_request_base_ref": "main",
        "reviewed_ci_workflow_name": "GrowthEvo CI",
        "reviewed_ci_workflow_path": ".github/workflows/ci.yml",
        "reviewed_ci_run_id": 246,
        "reviewed_ci_run_attempt": 1,
        "reviewed_ci_jobs": [
            {"name": name, "job_id": index, "status": "completed", "conclusion": "success"}
            for index, name in enumerate(GUARD._REQUIRED_CI_JOBS, start=1)
        ],
        "reviewed_ci_verified": True,
    }
    monkeypatch.setattr(
        GUARD,
        "_verify_reviewed_pr_and_ci",
        lambda **_kwargs: review,
    )

    payload = GUARD.verify_dispatch(
        trusted_ref="origin/main",
        trusted_branch="main",
        reason="explicit replication check",
    )

    assert payload["schema_version"] == "growthevo.research-dispatch.v1"
    assert payload["commit_sha"] == first
    assert payload["workflow_sha"] == first
    assert payload["workflow_sha_matches_commit"] is True
    assert payload["trusted_ref"] == "origin/main"
    assert payload["trusted_branch"] == "main"
    assert payload["trusted_ref_sha_at_dispatch"] == second
    assert payload["commit_is_trusted_ref_ancestor"] is True
    assert payload["experiment_reason"] == "explicit replication check"
    assert payload["reviewed_pull_request_number"] == 80
    assert payload["reviewed_ci_run_id"] == 246
    assert payload["reviewed_ci_verified"] is True


def test_unmerged_feature_commit_is_rejected(tmp_path: Path) -> None:
    repo, _, second = _repo(tmp_path)
    _git(repo, "checkout", "-b", "feature", second)
    feature = _commit(repo, "feature", "unreviewed\n")
    output = tmp_path / "dispatch.json"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo,
        env=_env(feature),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode != 0
    assert "is not part of trusted main history" in completed.stderr
    assert not output.exists()


def test_workflow_commit_must_match_evidence_commit(tmp_path: Path) -> None:
    repo, first, second = _repo(tmp_path)
    _git(repo, "checkout", "--detach", second)
    output = tmp_path / "dispatch.json"
    env = _env(second)
    env["GITHUB_WORKFLOW_SHA"] = first

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode != 0
    assert f"workflow commit {first} does not match evidence commit {second}" in completed.stderr
    assert not output.exists()


def test_non_dispatch_event_is_rejected_before_provenance(tmp_path: Path) -> None:
    repo, _, second = _repo(tmp_path)
    output = tmp_path / "dispatch.json"
    env = _env(second)
    env["GITHUB_EVENT_NAME"] = "pull_request"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode != 0
    assert "only accepts workflow_dispatch" in completed.stderr
    assert not output.exists()
