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


def _run(*, attempt: int = 1, conclusion: str = "success", path: str = ".github/workflows/ci.yml") -> dict[str, object]:
    return {
        "id": 244,
        "run_attempt": attempt,
        "head_sha": HEAD_SHA,
        "event": "pull_request",
        "name": "GrowthEvo CI",
        "path": path,
        "status": "completed",
        "conclusion": conclusion,
    }


def _jobs(*, failed: str | None = None, missing: str | None = None) -> list[dict[str, object]]:
    rows = []
    for index, name in enumerate(REQUIRED_JOBS, start=1):
        if name == missing:
            continue
        rows.append(
            {
                "id": 1000 + index,
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
) -> None:
    pulls = [_pull()] if pulls is None else pulls
    runs = [_run()] if runs is None else runs
    jobs = _jobs() if jobs is None else jobs

    def fake_github_json(path: str) -> object:
        if "/pulls?" in path:
            return pulls
        if path.endswith("/actions/runs?head_sha=" + HEAD_SHA + "&event=pull_request&per_page=100"):
            return {"workflow_runs": runs}
        if "/jobs?filter=latest&per_page=100" in path:
            return {"jobs": jobs}
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


def test_review_gate_rejects_stale_success_when_latest_ci_attempt_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api(
        monkeypatch,
        runs=[
            _run(attempt=1, conclusion="success"),
            _run(attempt=2, conclusion="failure"),
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


@pytest.mark.parametrize(
    ("jobs", "message"),
    [
        (_jobs(missing="package"), "exactly one latest job named 'package'"),
        (_jobs(failed="obd-integration"), "reviewed CI job 'obd-integration'.*not successful"),
    ],
)
def test_review_gate_requires_every_expected_ci_job(
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
