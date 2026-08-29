from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_stable_python_metadata_matches_ci_contract() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["requires-python"] == ">=3.11"

    classifiers = set(project["classifiers"])
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {version}" in classifiers

    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in ci
    assert 'python-version: "3.14"' in ci


def test_research_extras_do_not_overstate_frozen_environment_support() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = pyproject["project"]["optional-dependencies"]
    assert optional["obd"] == ["sb-obp==0.5.10; python_version < '3.13'"]
    assert "numpy==1.26.4" in optional["criteo"]

    policy = (ROOT / "docs" / "PYTHON_SUPPORT.md").read_text(encoding="utf-8")
    assert "Python 3.11–3.14" in policy
    assert "Python 3.12" in policy
    assert "accepted locked evidence" in policy
