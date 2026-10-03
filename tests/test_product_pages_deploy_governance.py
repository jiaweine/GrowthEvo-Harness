from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_production_deploy_is_main_only_and_least_privilege() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

    # Pull requests and workflow_dispatch runs from feature branches may build and
    # validate the static artifact, but only main may probe/configure/upload/deploy
    # the production GitHub Pages site.
    assert "id: pages-state" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert workflow.count("steps.pages-state.outputs.enabled == 'true'") == 2
    assert "needs.build.outputs.pages_enabled == 'true'" in workflow
    assert "permissions:\n  contents: read" in workflow

    # A fresh repository may not have a Pages site yet. That one-time admin state
    # must be reported as pending rather than turning every main build red.
    assert '"$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/pages"' in workflow
    assert 'if [[ "$STATUS" == "404" ]]' in workflow
    assert "GrowthEvo Pages deployment pending" in workflow
    assert "Settings → Pages → Build and deployment → Source → GitHub Actions" in workflow
    assert 'BUILD_TYPE' in workflow
    assert '"workflow"' in workflow

    # Pages/id-token write permissions remain scoped to the deploy job, not the
    # untrusted build/validation or bootstrap-detection work.
    assert workflow.count("pages: write") == 1
    assert workflow.count("id-token: write") == 1
