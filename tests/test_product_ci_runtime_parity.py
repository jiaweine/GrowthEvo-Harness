from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CONSTRAINT = "constraints/web-container-py313.txt"


def test_product_ci_uses_the_same_python_runtime_lock_as_production() -> None:
    for workflow_name in ("product-surface.yml", "product-stress.yml"):
        workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
        assert 'python-version: "3.13"' in workflow
        assert CONSTRAINT in workflow
        assert f"--constraint {CONSTRAINT} -e '.[web,dev]'" in workflow
        assert "cache-dependency-path:" in workflow
        assert "pyproject.toml" in workflow


def test_product_ci_does_not_float_web_runtime_independently() -> None:
    surface = (WORKFLOWS / "product-surface.yml").read_text(encoding="utf-8")
    stress = (WORKFLOWS / "product-stress.yml").read_text(encoding="utf-8")

    # Product-specific host tests may install the editable project for pytest,
    # but FastAPI/Uvicorn resolution must always be constrained to the same
    # Python 3.13 runtime graph used by the production Docker image.
    assert "Install production-aligned web product dependencies" in surface
    assert "Install production-aligned test dependencies" in stress
    assert "python-version: \"3.12\"" not in surface
    assert "python-version: \"3.12\"" not in stress
