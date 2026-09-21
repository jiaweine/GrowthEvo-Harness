from __future__ import annotations

from pathlib import Path
import tomllib

from growthevo.evolution.pypi_provenance import PYPI_ATTESTATIONS_VERSION
from growthevo.evolution.sigstore_attestation import SIGSTORE_SDK_VERSION


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
    assert "out of public issues and pull requests" in policy
    assert "private vulnerability-reporting flow" in policy
    assert "Security contact request" in policy
    assert "accepted locked benchmark artifacts" in policy
    assert "new preregistered experiment identity" in policy



def test_attestation_extras_match_runtime_verifier_versions() -> None:
    optional = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"]

    sigstore_requirement = f"sigstore=={SIGSTORE_SDK_VERSION}"
    pypi_requirement = f"pypi-attestations=={PYPI_ATTESTATIONS_VERSION}"

    assert optional["attestation-sigstore"] == [sigstore_requirement]
    assert set(optional["attestation-pypi"]) == {
        pypi_requirement,
        sigstore_requirement,
    }
