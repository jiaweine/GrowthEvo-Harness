from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_product_required_workflows_run_for_every_main_pull_request() -> None:
    for name in (
        "product-auth.yml",
        "product-persistence.yml",
        "product-stress.yml",
        "product-surface.yml",
    ):
        workflow = _workflow(name)
        assert re.search(r"(?m)^\s{2}pull_request:\n\s{4}branches: \[main\]$", workflow), name
        assert not re.search(r"(?m)^\s{2}pull_request:\n(?:\s{4}.*\n)*?\s{4}paths:", workflow), name


def test_product_required_workflows_revalidate_main_pushes() -> None:
    for name in (
        "product-auth.yml",
        "product-persistence.yml",
        "product-stress.yml",
        "product-surface.yml",
    ):
        workflow = _workflow(name)
        assert re.search(r"(?m)^\s{2}push:\n\s{4}branches: \[main\]$", workflow), name


def test_codeql_exposes_stable_required_aggregator_without_path_filtered_trigger() -> None:
    workflow = _workflow("codeql.yml")
    assert re.search(r"(?m)^\s{2}pull_request:\n\s{4}branches: \[main\]$", workflow)
    assert "name: codeql-required" in workflow
    assert "tools/ci_changed_paths.py --profile codeql" in workflow
    assert "needs: [changes, analyze]" in workflow


def test_required_product_and_supply_chain_job_names_are_stable() -> None:
    expected = {
        "product-auth.yml": ("oidc-jwks-production",),
        "product-persistence.yml": ("postgres-product",),
        "product-stress.yml": ("stress",),
        "product-surface.yml": ("web-product", "mobile"),
        "slsa-build-provenance.yml": ("real-slsa-build-provenance",),
        "pypi-provenance.yml": ("real-pypi-provenance",),
    }
    for workflow_name, jobs in expected.items():
        workflow = _workflow(workflow_name)
        for job in jobs:
            assert re.search(rf"(?m)^\s{{2}}{re.escape(job)}:$", workflow), (workflow_name, job)
