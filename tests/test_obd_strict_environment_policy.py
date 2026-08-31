from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_obd_ci_environment.py"
VERIFIER = ROOT / "scripts" / "verify_frozen_environment.py"


def test_shared_obd_bootstrap_rejects_unexpected_distributions() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    verifier = VERIFIER.read_text(encoding="utf-8")

    assert "find_unexpected_distributions" in bootstrap
    assert "unexpected_distributions=" in bootstrap
    assert "unexpected installed distribution" in bootstrap
    assert 'DEFAULT_ALLOWED_EXTRA_DISTRIBUTIONS = frozenset({"pip", "growthevo-harness"})' in verifier
    assert "find_unexpected_distributions(pins)" in verifier
