from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_regular_ci_uses_node24_native_actions_and_builds_distribution() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v7" in ci
    assert "actions/setup-python@v7" in ci
    assert "actions/upload-artifact@v7" in ci
    assert "actions/checkout@v4" not in ci
    assert "actions/setup-python@v5" not in ci
    assert "actions/upload-artifact@v4" not in ci
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in ci
    assert 'python-version: "3.14"' in ci
    assert "  package:\n" in ci
    assert "python -m build" in ci
    assert "python -m twine check dist/*" in ci
    assert "growthevo-locked-ope --help" in ci
    assert "growthevo-locked-targeting --help" in ci


def test_accepted_full_data_workflows_are_manual_only() -> None:
    for filename in (
        "full-criteo-pr-validation.yml",
        "full-obd-pr-validation.yml",
    ):
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "workflow_dispatch:" in workflow
        assert "experiment_reason:" in workflow
        assert "pull_request:" not in workflow
        assert "cancel-in-progress: false" in workflow
        assert "actions/checkout@v7" in workflow
        assert "actions/setup-python@v7" in workflow
        assert "actions/upload-artifact@v7" in workflow
