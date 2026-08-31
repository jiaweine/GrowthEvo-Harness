from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_research_dispatch.py"


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


def test_historical_main_commit_is_allowed_and_persisted(tmp_path: Path) -> None:
    repo, first, second = _repo(tmp_path)
    _git(repo, "checkout", "--detach", first)
    output = tmp_path / "dispatch.json"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo,
        env=_env(first),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "growthevo.research-dispatch.v1"
    assert payload["commit_sha"] == first
    assert payload["workflow_sha"] == first
    assert payload["workflow_sha_matches_commit"] is True
    assert payload["trusted_ref"] == "origin/main"
    assert payload["trusted_ref_sha_at_dispatch"] == second
    assert payload["commit_is_trusted_ref_ancestor"] is True
    assert payload["experiment_reason"] == "explicit replication check"


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
