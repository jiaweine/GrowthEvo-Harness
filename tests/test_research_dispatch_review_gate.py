from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_research_dispatch.py"
SPEC = importlib.util.spec_from_file_location("research_dispatch_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)

MERGE_SHA = "6" * 40
HEAD_SHA = "a" * 40
REPOSITORY = "jiaweine/GrowthEvo-Harness"
REQUIRED_JOBS = (
    "test (3.11)",
    "test (3.12)",
    "test (3.13)",
    "test (3.14)",
    "package",
    "obd-integration",
)


def _pull(*, base_ref: str = "main", merge_sha: str = MERGE_SHA) -> dict[str, object]:
    return {
        "number": 79,
        "html_url": "https://github.com/jiaweine/GrowthEvo-Harness/pull/79",
        "merged_at": "2026-09-01T00:00:00Z",
        "merge_commit_sha": merge_sha,
        "base": {"ref": base_ref},
        "head": {"sha": HEAD_SHA},
    }


def _run(
    *,
    run_id: int = 244,
    attempt: int = 1,
    conclusion: str = "success",
    path: str = ".github/workflows/ci.yml",
    head_sha: str = HEAD_SHA,
    event: str = "pull_request",
    head_branch: str = "feature",
    pull_request_number: int | None = 79,
) -> dict[str, object]:
    pull_requests: list[dict[str, int]] = []
    if pull_request_number is not None:
        pull_requests.append({"number": pull_request_number})
    return {
        "id": run_id,
        "run_attempt": attempt,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "event": event,
        "name": "GrowthEvo CI",
        "path": path,
        "status": "completed",
        "conclusion": conclusion,
        "pull_requests": pull_requests,
    }


def _push_run(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "run_id": 344,
        "head_sha": MERGE_SHA,
        "event": "push",
        "head_branch": "main",
        "pull_request_number": None,
    }
    values.update(overrides)
    return _run(**values)  # type: ignore[arg-type]


def _jobs(*, failed: str | None = None, missing: str | None = None, offset: int = 1000) -> list[dict[str, object]]:
    rows = []
    for index, name in enumerate(REQUIRED_JOBS, start=1):
        if name == missing:
            continue
        rows.append(
            {
                "id": offset + index,
                "name": name,
                "status": "completed",
                "conclusion": "failure" if name == failed else "success",
            }
        )
    return rows


def _install_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pulls: list[dict[str, object]] | None = None,
    runs: list[dict[str, object]] | None = None,
    jobs: list[dict[str, object]] | None = None,
    push_runs: list[dict[str, object]] | None = None,
    push_jobs: list[dict[str, object]] | None = None,
) -> None:
    pulls = [_pull()] if pulls is None else pulls
    runs = [_run()] if runs is None else runs
    jobs = _jobs() if jobs is None else jobs
    push_runs = [_push_run()] if push_runs is None else push_runs
    push_jobs = _jobs(offset=2000) if push_jobs is None else push_jobs
    pr_run_ids = {row["id"] for row in runs if isinstance(row.get("id"), int)}
    push_run_ids = {row["id"] for row in push_runs if isinstance(row.get("id"), int)}

    def fake_github_json(path: str) -> object:
        if "/pulls?" in path:
            return pulls
        if path.endswith("/actions/runs?head_sha=" + HEAD_SHA + "&event=pull_request&per_page=100"):
            return {"workflow_runs": runs}
        if path.endswith("/actions/runs?head_sha=" + MERGE_SHA + "&event=push&per_page=100"):
            return {"workflow_runs": push_runs}
        if "/jobs?filter=latest&per_page=100" in path:
            if any(f"/actions/runs/{run_id}/jobs?" in path for run_id in pr_run_ids):
                return {"jobs": jobs}
            if any(f"/actions/runs/{run_id}/jobs?" in path for run_id in push_run_ids):
                return {"jobs": push_jobs}
        raise AssertionError(f"unexpected GitHub API path: {path}")

    monkeypatch.setattr(GUARD, "_github_json", fake_github_json)


def test_review_gate_accepts_exact_merged_main_pr_with_green_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch)

    result = GUARD._verify_reviewed_pr_and_ci(
        repository=REPOSITORY,
        expected_sha=MERGE_SHA,
        trusted_branch="main",
    )

    assert result["reviewed_pull_request_number"] == 79
    assert result["reviewed_pull_request_head_sha"] == HEAD_SHA
    assert result["reviewed_pull_request_merge_sha"] == MERGE_SHA
    assert result["reviewed_ci_run_id"] == 244
    assert result["reviewed_ci_verified"] is True
    assert [job["name"] for job in result["reviewed_ci_jobs"]] == list(REQUIRED_JOBS)
    assert result["landed_main_ci_commit_sha"] == MERGE_SHA
    assert result["landed_main_ci_event"] == "push"
    assert result["landed_main_ci_branch"] == "main"
    assert result["landed_main_ci_run_id"] == 344
    assert result["landed_main_ci_verified"] is True
    assert [job["name"] for job in result["landed_main_ci_jobs"]] == list(REQUIRED_JOBS)


def test_review_gate_rejects_direct_push_without_merged_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch, pulls=[])

    with pytest.raises(RuntimeError, match="merge commit of exactly one merged PR"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


@pytest.mark.parametrize(
    ("pull", "message"),
    [
        (_pull(base_ref="dev"), "merged PR into main"),
        (_pull(merge_sha="7" * 40), "merged PR into main"),
    ],
)
def test_review_gate_rejects_wrong_merge_identity(
    monkeypatch: pytest.MonkeyPatch,
    pull: dict[str, object],
    message: str,
) -> None:
    _install_api(monkeypatch, pulls=[pull])

    with pytest.raises(RuntimeError, match=message):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_prefers_newer_failed_run_over_older_rerun_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(
        monkeypatch,
        runs=[
            _run(run_id=244, attempt=2, conclusion="success"),
            _run(run_id=245, attempt=1, conclusion="failure"),
        ],
    )

    with pytest.raises(RuntimeError, match="latest GrowthEvo CI run.*not successful"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_rejects_lookalike_workflow_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch, runs=[_run(path=".github/workflows/fake.yml")])

    with pytest.raises(RuntimeError, match="no GrowthEvo CI pull-request run"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_rejects_ci_from_different_pr_with_same_head_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch, runs=[_run(pull_request_number=78)])

    with pytest.raises(RuntimeError, match="no GrowthEvo CI pull-request run"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


@pytest.mark.parametrize(
    ("jobs", "message"),
    [
        (_jobs(missing="package"), "exactly one latest job named 'package'"),
        (_jobs(failed="obd-integration"), "reviewed PR head CI job 'obd-integration'.*not successful"),
    ],
)
def test_review_gate_requires_every_expected_pr_ci_job(
    monkeypatch: pytest.MonkeyPatch,
    jobs: list[dict[str, object]],
    message: str,
) -> None:
    _install_api(monkeypatch, jobs=jobs)

    with pytest.raises(RuntimeError, match=message):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_rejects_missing_exact_main_push_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch, push_runs=[])

    with pytest.raises(RuntimeError, match="landed main commit.*no GrowthEvo CI push run"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_rejects_push_ci_from_different_branch_with_same_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(monkeypatch, push_runs=[_push_run(head_branch="release")])

    with pytest.raises(RuntimeError, match="landed main commit.*no GrowthEvo CI push run"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_review_gate_rejects_failed_exact_main_push_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(
        monkeypatch,
        push_runs=[_push_run(run_id=344, conclusion="success"), _push_run(run_id=345, conclusion="failure")],
    )

    with pytest.raises(RuntimeError, match="latest GrowthEvo CI run for landed main commit.*not successful"):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


@pytest.mark.parametrize(
    ("push_jobs", "message"),
    [
        (_jobs(missing="package", offset=2000), "landed main commit CI run.*exactly one latest job named 'package'"),
        (_jobs(failed="obd-integration", offset=2000), "landed main commit CI job 'obd-integration'.*not successful"),
    ],
)
def test_review_gate_requires_every_expected_exact_main_ci_job(
    monkeypatch: pytest.MonkeyPatch,
    push_jobs: list[dict[str, object]],
    message: str,
) -> None:
    _install_api(monkeypatch, push_jobs=push_jobs)

    with pytest.raises(RuntimeError, match=message):
        GUARD._verify_reviewed_pr_and_ci(
            repository=REPOSITORY,
            expected_sha=MERGE_SHA,
            trusted_branch="main",
        )


def test_full_data_workflows_run_review_gate_before_benchmark() -> None:
    cases = (
        ("full-criteo-pr-validation.yml", "Run full preregistered Criteo benchmark"),
        ("full-obd-pr-validation.yml", "Run full preregistered Open Bandit benchmark"),
    )
    for filename, benchmark_step in cases:
        workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        guard = "python scripts/verify_research_dispatch.py"
        assert guard in workflow
        assert workflow.index(guard) < workflow.index(benchmark_step)
