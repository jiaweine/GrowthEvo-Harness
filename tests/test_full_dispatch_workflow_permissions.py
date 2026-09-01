from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_full_data_dispatch_guard_has_only_required_read_permissions_and_token_scope() -> None:
    for filename in (
        "full-criteo-pr-validation.yml",
        "full-obd-pr-validation.yml",
    ):
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        permissions = workflow.split("permissions:\n", maxsplit=1)[1].split(
            "\nconcurrency:\n", maxsplit=1
        )[0]
        assert permissions == (
            "  contents: read\n"
            "  actions: read\n"
            "  pull-requests: read\n"
        )

        guard_step = workflow.split(
            "      - name: Verify reviewed main-history dispatch\n", maxsplit=1
        )[1].split("\n      - name:", maxsplit=1)[0]
        assert "GITHUB_TOKEN: ${{ github.token }}" in guard_step
        assert "python scripts/verify_research_dispatch.py" in guard_step

        before_guard, after_guard = workflow.split(
            "      - name: Verify reviewed main-history dispatch\n", maxsplit=1
        )
        _, after_guard_step = after_guard.split("\n      - name:", maxsplit=1)
        assert "GITHUB_TOKEN: ${{ github.token }}" not in before_guard
        assert "GITHUB_TOKEN: ${{ github.token }}" not in after_guard_step
