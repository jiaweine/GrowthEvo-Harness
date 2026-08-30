from __future__ import annotations

from pathlib import Path
import tomllib

import growthevo


ROOT = Path(__file__).resolve().parents[1]


def test_package_has_discovery_urls_and_research_keywords() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    assert growthevo.__version__ == "0.1.0"
    assert set(project["urls"]) == {"Repository", "Issues", "Documentation", "Changelog"}
    assert project["urls"]["Repository"] == "https://github.com/jiaweine/GrowthEvo-Harness"
    assert project["urls"]["Issues"].endswith("/GrowthEvo-Harness/issues")
    assert project["urls"]["Changelog"].endswith("/blob/main/CHANGELOG.md")
    keywords = set(project["keywords"])
    assert {"causal-inference", "reinforcement-learning", "off-policy-evaluation"} <= keywords


def test_release_process_files_are_present_and_evidence_aware() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")

    assert "## Unreleased" in changelog
    assert "7d538cea9698b5f0a48c585eed85e3ae526e5af6" in changelog
    assert "7ac26a5aebde2c70e1b43264b89f08dddcff0245" in changelog
    assert "Accepted final holdouts are not tuning sets." in contributing
    assert "new experiment identity" in contributing
    assert "Choose and add a LICENSE" in checklist
    assert "Protect `main`" in checklist
    assert "workflow_dispatch" not in template  # contributor checklist stays implementation-agnostic
    assert "Only the frozen winner reaches final holdout." in template
