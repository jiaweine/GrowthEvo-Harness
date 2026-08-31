from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_regular_ci_verifies_pull_requests_and_every_push_to_main() -> None:
    ci = CI.read_text(encoding="utf-8")
    trigger = ci.split("permissions:\n", maxsplit=1)[0]

    assert "  pull_request:\n    branches: [main]\n" in trigger
    assert "  push:\n    branches: [main]\n" in trigger
    assert "paths:" not in trigger
    assert "paths-ignore:" not in trigger


def test_obd_evidence_commit_sha_works_for_pr_and_push_events() -> None:
    ci = CI.read_text(encoding="utf-8")
    fallback = "${{ github.event.pull_request.head.sha || github.sha }}"

    assert '"--commit-sha", "${{ github.event.pull_request.head.sha }}"' not in ci
    assert f'"--commit-sha", "{fallback}"' in ci
