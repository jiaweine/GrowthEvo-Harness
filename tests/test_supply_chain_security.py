from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_tracks_github_actions_without_touching_research_pins() -> None:
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in config
    assert 'directory: "/"' in config
    assert 'interval: "weekly"' in config
    assert 'package-ecosystem: "pip"' not in config


def test_security_policy_uses_private_reporting_and_preserves_evidence_boundary() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Report a vulnerability" in policy
    assert "do **not** publish exploit details" in policy
    assert "Security contact request" in policy
    assert "locked benchmark artifacts" in policy
    assert "new preregistered experiment identity" in policy
