from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_production_deploy_is_main_only_and_least_privilege() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

    # Pull requests and workflow_dispatch runs from feature branches may build and
    # validate the static artifact, but only main is allowed to configure/upload/
    # deploy the production GitHub Pages site.
    assert workflow.count("if: github.ref == 'refs/heads/main'") == 3
    assert "permissions:\n  contents: read" in workflow

    # Pages/id-token write permissions must remain scoped to the deploy job, not
    # the workflow-level token used by untrusted build/validation work.
    assert workflow.count("pages: write") == 1
    assert workflow.count("id-token: write") == 1
