from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "full-criteo-pr-validation.yml"
ACCEPTED_ENVIRONMENT = (
    ROOT
    / "benchmarks"
    / "targeting"
    / "results"
    / "criteo-v2.1-visit-top10"
    / "7ac26a5a"
    / "environment.txt"
)
FROZEN_ENV_VERIFIER = ROOT / "scripts" / "verify_frozen_environment.py"


def test_full_criteo_replication_is_constrained_to_the_accepted_environment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    accepted = ACCEPTED_ENVIRONMENT.read_text(encoding="utf-8")
    accepted_path = (
        "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/environment.txt"
    )
    constraints_path = "/tmp/growthevo-full-criteo/accepted-constraints.txt"
    verifier_command = 'python scripts/verify_frozen_environment.py "$ACCEPTED_ENVIRONMENT"'

    assert FROZEN_ENV_VERIFIER.is_file()
    assert "lightgbm==4.7.0" in accepted
    assert "numpy==1.26.4" in accepted
    assert "pandas==2.3.3" in accepted
    assert "scikit-learn==1.9.0" in accepted
    assert "joblib==1.5.3" in accepted
    assert "scipy==1.17.1" in accepted

    assert f"ACCEPTED_ENVIRONMENT: {accepted_path}" in workflow
    assert "cache-dependency-path: |\n            pyproject.toml\n" in workflow
    assert accepted_path in workflow
    assert "Install frozen Criteo research environment" in workflow
    assert f"--constraint {constraints_path}" in workflow
    assert verifier_command in workflow
    assert workflow.index(verifier_command) < workflow.index(
        "Exercise all five CATE learners before real data"
    )
    assert workflow.index(verifier_command) < workflow.index(
        "Run full preregistered Criteo benchmark"
    )
    assert constraints_path in workflow.split(
        "Upload full Criteo research evidence", maxsplit=1
    )[1]
