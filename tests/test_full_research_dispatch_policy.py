from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "full-criteo-pr-validation.yml",
    ROOT / ".github" / "workflows" / "full-obd-pr-validation.yml",
)


def test_full_data_workflows_require_reviewed_main_history_before_benchmark() -> None:
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in text
        assert "pull_request:" not in text
        assert "EXPERIMENT_REASON: ${{ inputs.experiment_reason }}" in text
        assert "fetch-depth: 0" in text
        assert "git fetch --no-tags origin '+refs/heads/main:refs/remotes/origin/main'" in text
        assert "python scripts/verify_research_dispatch.py" in text
        assert "dispatch-provenance.json" in text

        guard = text.index("- name: Verify reviewed main-history dispatch")
        if "Run full preregistered Criteo benchmark" in text:
            benchmark = text.index("- name: Run full preregistered Criteo benchmark")
            upload_path = "/tmp/growthevo-full-criteo/dispatch-provenance.json"
        else:
            benchmark = text.index("- name: Run full preregistered Open Bandit benchmark")
            upload_path = "/tmp/growthevo-full-obd/dispatch-provenance.json"
        assert guard < benchmark
        assert upload_path in text


def test_dispatch_guard_records_auditable_github_run_identity() -> None:
    script = (ROOT / "scripts" / "verify_research_dispatch.py").read_text(encoding="utf-8")
    for variable in (
        "GITHUB_REPOSITORY",
        "GITHUB_ACTOR",
        "GITHUB_TRIGGERING_ACTOR",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_REF",
        "GITHUB_REF_NAME",
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
    ):
        assert variable in script
    assert 'SCHEMA_VERSION = "growthevo.research-dispatch.v1"' in script
    assert '"experiment_reason": reason' in script
    assert '"commit_is_trusted_ref_ancestor": True' in script
